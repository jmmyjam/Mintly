"""CLIP image embeddings for the camera scanner.

Each catalog card's artwork is embedded once (by `scripts/embed_catalog.py`) into
a 512-d unit vector stored in `card_catalog.embedding`. A scan embeds the
uploaded photo the same way and finds the nearest catalog cards by cosine
similarity — matching on *artwork*, which survives glare/blur/angle far better
than reading the card's text.

Model: `clip-ViT-B-32` (sentence-transformers / PyTorch, CPU). Validated with a
degraded-photo proxy: the true card ranked #1 for every test image.

At ~20k cards the search is an in-memory brute-force dot product (sub-ms), so no
pgvector is needed. The model and the catalog matrix are cached process-wide (the
api runs a single worker); CPU inference is offloaded to FastAPI's threadpool by
the sync `def` scan route.

Readiness: loading the model cold costs ~4s of torch import + model load, so the
api starts a keep-warm thread at startup (`start_keep_warm`) that loads it and
the matrix before anyone scans, then keeps both warm. The lazy loads below stay
as the fallback when that thread isn't running (tests, `SCAN_WARMUP=0`).
"""
import io
import logging
import threading
import time
from typing import Callable

import numpy as np
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app.models import CatalogCard

logger = logging.getLogger(__name__)

MODEL_NAME = "clip-ViT-B-32"
EMBED_DIM = 512
_CACHE_TTL = 6 * 3600  # seconds; the matrix only changes when the backfill runs
# The keep-warm thread rebuilds the matrix well inside _CACHE_TTL, so a scan never
# finds it expired and pays the rebuild itself; the TTL only bites without it.
_MATRIX_REFRESH = 3600
_KEEP_WARM_INTERVAL = 5 * 60

_model = None
_model_lock = threading.Lock()

# Catalog matrix cache: parallel `ids` + an (N, EMBED_DIM) float32 matrix of
# L2-normalised row vectors, so `matrix @ query` is cosine similarity.
_cache: dict = {"ts": 0.0, "ids": [], "matrix": None}
_cache_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                # Heavy import (torch) — deferred so importing this module (e.g.
                # in tests that monkeypatch it) stays cheap.
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_pil(img: Image.Image) -> np.ndarray:
    """Embed one PIL image to an L2-normalised float32 vector."""
    return embed_pils([img])[0]


def embed_pils(imgs: list[Image.Image]) -> np.ndarray:
    """Embed a batch of PIL images -> (N, EMBED_DIM) float32, L2-normalised."""
    model = _get_model()
    vecs = model.encode(
        [im.convert("RGB") for im in imgs],
        normalize_embeddings=True,
        convert_to_numpy=True,
        batch_size=16,
    )
    return vecs.astype(np.float32)


def embed_query(data: bytes) -> list[np.ndarray] | None:
    """Embed an uploaded scan image AND its horizontal mirror. Returning both
    orientations makes the match robust to selfie-mirrored front cameras — the
    caller scores against the best of the two. Returns None if the bytes don't
    decode as an image."""
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None
    return [embed_pil(img), embed_pil(ImageOps.mirror(img))]


def _load_matrix(db: Session) -> tuple[list[str], np.ndarray]:
    rows = (
        db.query(CatalogCard.card_id, CatalogCard.embedding)
        .filter(CatalogCard.embedding.isnot(None))
        .all()
    )
    ids: list[str] = []
    vecs: list[np.ndarray] = []
    for card_id, blob in rows:
        if not blob:
            continue
        v = np.frombuffer(blob, dtype=np.float32)
        if v.size != EMBED_DIM:
            continue
        ids.append(card_id)
        vecs.append(v)
    matrix = np.vstack(vecs) if vecs else np.zeros((0, EMBED_DIM), dtype=np.float32)
    return ids, matrix


def catalog_matrix(db: Session) -> tuple[list[str], np.ndarray]:
    """The cached (ids, matrix) of all stored embeddings, built on demand if cold
    or expired."""
    with _cache_lock:
        if _cache["matrix"] is not None and time.monotonic() - _cache["ts"] <= _CACHE_TTL:
            return _cache["ids"], _cache["matrix"]
    return refresh_matrix(db)


def refresh_matrix(db: Session) -> tuple[list[str], np.ndarray]:
    """Rebuild the matrix from the DB and swap it in. The load (~0.5s at 20k
    cards) runs outside the lock, so a background refresh never stalls a scan
    that can keep using the current matrix meanwhile."""
    ids, matrix = _load_matrix(db)
    with _cache_lock:
        _cache.update(ts=time.monotonic(), ids=ids, matrix=matrix)
    return ids, matrix


def reset_cache() -> None:
    """Drop the cached matrix (tests; or force a reload after a backfill)."""
    with _cache_lock:
        _cache.update(ts=0.0, ids=[], matrix=None)


def nearest(db: Session, query_vecs: list[np.ndarray], k: int = 12) -> list[tuple[str, float]]:
    """Top-k catalog cards by best cosine over the given query orientations."""
    ids, matrix = catalog_matrix(db)
    if matrix is None or matrix.shape[0] == 0 or not query_vecs:
        return []
    scores = None
    for q in query_vecs:
        s = matrix @ q
        scores = s if scores is None else np.maximum(scores, s)
    k = min(k, scores.shape[0])
    top = np.argpartition(-scores, k - 1)[:k]
    top = top[np.argsort(-scores[top])]
    return [(ids[i], float(scores[i])) for i in top]


# ---- Keep-warm -------------------------------------------------------------

_keep_warm_started = False
_keep_warm_lock = threading.Lock()


def keep_warm_tick(db: Session) -> None:
    """One keep-warm pass: refresh the matrix when due, then run a throwaway
    embedding so the model is loaded before the first real scan."""
    with _cache_lock:
        due = _cache["matrix"] is None or time.monotonic() - _cache["ts"] >= _MATRIX_REFRESH
        matrix = _cache["matrix"]
    if due:
        _, matrix = refresh_matrix(db)
    # With nothing to match against (fresh DB, a dev machine without the
    # backfill) a scan is pointless, so don't spend ~500MB of RAM on torch for it.
    # A later refresh that finds embeddings warms the model then.
    if matrix.shape[0] == 0:
        return
    # Repeating this every tick is deliberate: a forward pass touches torch's
    # file-backed code pages (and every weight), so the kernel won't reclaim them
    # during long idle stretches while the daily crawl and nightly pg_dump churn
    # the page cache. It costs ~0.1s of CPU per tick.
    embed_pil(Image.new("RGB", (224, 224)))


def start_keep_warm(session_factory: Callable[[], Session]) -> None:
    """Start the daemon keep-warm thread (idempotent). Called from app startup;
    the first tick runs immediately so the model loads right after a deploy."""
    global _keep_warm_started
    with _keep_warm_lock:
        if _keep_warm_started:
            return
        _keep_warm_started = True

    def run():
        while True:
            try:
                db = session_factory()
                try:
                    keep_warm_tick(db)
                finally:
                    db.close()
            except Exception:
                # Never let a DB hiccup or a missing model kill the thread; the
                # scan route's lazy loads still work, and the next tick retries.
                logger.warning("scanner keep-warm tick failed", exc_info=True)
            time.sleep(_KEEP_WARM_INTERVAL)

    threading.Thread(target=run, name="scan-keep-warm", daemon=True).start()
