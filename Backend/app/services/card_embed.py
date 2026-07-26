"""CLIP image embeddings for the camera scanner.

Each catalog card's artwork is embedded once (by `scripts/embed_catalog.py`) into
a 512-d unit vector stored in `card_catalog.embedding`. A scan embeds the
uploaded photo the same way and finds the nearest catalog cards by cosine
similarity — matching on *artwork*, which survives glare/blur/angle far better
than reading the card's text.

Model: `clip-ViT-B-32` (sentence-transformers / PyTorch, CPU). Validated with a
degraded-photo proxy: the true card ranked #1 for every test image.

At ~20k cards the search is an in-memory brute-force dot product (sub-ms), so no
pgvector is needed. The model and the catalog matrix are lazily loaded and
cached process-wide (the api runs a single worker); CPU inference is offloaded
to FastAPI's threadpool by the sync `def` scan route.
"""
import io
import threading
import time

import numpy as np
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app.models import CatalogCard

MODEL_NAME = "clip-ViT-B-32"
EMBED_DIM = 512
_CACHE_TTL = 6 * 3600  # seconds; the matrix only changes when the backfill runs

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
    """Lazily build + cache the (ids, matrix) of all stored embeddings."""
    now = time.monotonic()
    with _cache_lock:
        if _cache["matrix"] is None or now - _cache["ts"] > _CACHE_TTL:
            ids, matrix = _load_matrix(db)
            _cache.update(ts=now, ids=ids, matrix=matrix)
        return _cache["ids"], _cache["matrix"]


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
