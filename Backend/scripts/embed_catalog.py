"""Backfill CLIP image embeddings for catalog cards, backing the camera scanner.

For each catalog card, download its artwork and store a CLIP embedding in
`card_catalog.embedding`. Only cards missing an embedding are processed (so it's
cheap to re-run as new cards appear); `--all` recomputes every card. Runs
straight against the DB — no FastAPI app needed — like `snapshot_all.py`.

Runs on the server, in the api container (which has the model baked in):
    docker compose exec -T api python scripts/embed_catalog.py

One-time backfill of ~20k images takes a while (download-bound); afterwards the
daily crawl adds only a handful of new cards, so a weekly run keeps it current.
The api process picks up new embeddings within its cache TTL (or on restart).

    venv/bin/python scripts/embed_catalog.py               # missing only
    venv/bin/python scripts/embed_catalog.py --limit 200   # smoke test
    venv/bin/python scripts/embed_catalog.py --all         # recompute everything
"""
import argparse
import io
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import certifi
import numpy as np
import requests
from PIL import Image

# Run as a plain script — put Backend/ on the path so `app` imports (matches
# snapshot_all.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal  # noqa: E402
from app.models import CatalogCard  # noqa: E402
from app.services import card_embed  # noqa: E402

_session = requests.Session()
_session.headers["User-Agent"] = "Mintly/1.0"
_CARD_BACK = (640, 892)  # pokemontcg.io serves a 404 card-back PNG at this size


def _image_url(data: dict | None) -> str | None:
    images = (data or {}).get("images") or {}
    return images.get("large") or images.get("small")


def _fetch(url: str | None) -> Image.Image | None:
    if not url:
        return None
    try:
        r = _session.get(url, timeout=20, verify=certifi.where())
        if r.status_code != 200:  # a 404 still returns the card-back PNG — skip it
            return None
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        if img.size == _CARD_BACK:
            return None
        return img
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill CLIP image embeddings for catalog cards")
    ap.add_argument("--all", action="store_true", help="recompute every card, not just missing ones")
    ap.add_argument("--limit", type=int, default=0, help="cap the number of cards processed")
    ap.add_argument("--chunk", type=int, default=64, help="cards per download+encode+commit chunk")
    ap.add_argument("--workers", type=int, default=8, help="concurrent image downloads")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        q = db.query(CatalogCard)
        if not args.all:
            q = q.filter(CatalogCard.embedding.is_(None))
        q = q.order_by(CatalogCard.card_id)
        if args.limit:
            q = q.limit(args.limit)
        rows = q.all()
        total = len(rows)
        print(f"embedding {total} card image(s)", flush=True)

        done = skipped = 0
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for start in range(0, total, args.chunk):
                chunk = rows[start : start + args.chunk]
                imgs = list(pool.map(_fetch, (_image_url(r.data) for r in chunk)))
                batch = [(r, im) for r, im in zip(chunk, imgs) if im is not None]
                if batch:
                    vecs = card_embed.embed_pils([im for _, im in batch])
                    for (r, _im), v in zip(batch, vecs):
                        r.embedding = np.asarray(v, dtype=np.float32).tobytes()
                    done += len(batch)
                skipped += len(chunk) - len(batch)
                db.commit()
                elapsed = time.time() - t0 or 1e-9
                print(
                    f"  {min(start + args.chunk, total)}/{total}  "
                    f"embedded={done} skipped={skipped}  ({(start + len(chunk)) / elapsed:.1f}/s)",
                    flush=True,
                )
        print(f"done: {done} embedded, {skipped} skipped in {time.time() - t0:.0f}s", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
