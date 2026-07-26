"""Camera scanner endpoint: POST /scan.

Takes an uploaded card photo, embeds it (CLIP), and returns the nearest catalog
cards for the user to confirm. Runs entirely on our own hardware — no per-scan
cost, so the feature is free at any scale. Reuses the same price-change /
estimate annotation as the browse pages so the scan result tiles look identical.

The route is a sync `def`, so FastAPI runs it in its threadpool — the CPU-bound
embedding must not block the single-worker event loop.
"""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.auth import get_current_user
from app.services import card_catalog, card_embed
from app.services.price_history import annotate_price_changes, attach_estimates
from app.services.rate_limit import rate_limit

logger = logging.getLogger(__name__)

# Login-only: the scanner is an account feature (you scan to add to a portfolio),
# and gating the compute-heavy embedding behind a valid JWT keeps it off limits to
# anonymous callers. Plus its own generous per-IP scope — an abuse guard for a
# compute-heavy endpoint, not a usage cap (meant to be unlimited for real users).
router = APIRouter(
    dependencies=[
        Depends(get_current_user),
        Depends(rate_limit("scan", times=60, seconds=60, what="scans")),
    ]
)

_MAX_BYTES = 8 * 1024 * 1024
_TOP_K = 12


@router.post("/scan")
def scan(file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="No image was received")
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image is too large")

    query_vecs = card_embed.embed_query(data)
    if not query_vecs:
        raise HTTPException(status_code=400, detail="That image couldn't be read")

    ranked = card_embed.nearest(db, query_vecs, k=_TOP_K)
    rows = card_catalog.get_cards(db, [card_id for card_id, _ in ranked])
    cards = [card_catalog.card_payload(rows[cid]) for cid, _ in ranked if cid in rows]

    # Same best-effort snapshot + daily-change + eBay-estimate annotation the
    # browse pages apply, so scan tiles render identically.
    try:
        annotate_price_changes(db, cards)
        attach_estimates(db, cards)
    except Exception:
        db.rollback()
        logger.warning("scan price annotation failed", exc_info=True)

    return {"data": cards, "page": 1, "pageSize": len(cards), "totalCount": len(cards)}
