"""Camera scanner endpoint: POST /scan.

Takes an uploaded card photo, embeds it (CLIP), and returns the nearest catalog
cards for the user to confirm. Runs entirely on our own hardware — no per-scan
cost, so the feature is free at any scale. Reuses the same price-change /
estimate annotation as the browse pages so the scan result tiles look identical.

The route is a sync `def`, so FastAPI runs it in its threadpool — the CPU-bound
embedding must not block the single-worker event loop.
"""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ScanFeedback
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
    # Keep the cosine similarity per card (batch scan uses it to flag shaky
    # best-guesses for review); it's in [-1, 1], higher = closer artwork.
    cards = []
    for cid, score in ranked:
        row = rows.get(cid)
        if row is None:
            continue
        payload = card_catalog.card_payload(row)
        payload["matchScore"] = round(float(score), 4)
        cards.append(payload)

    # Same best-effort snapshot + daily-change + eBay-estimate annotation the
    # browse pages apply, so scan tiles render identically.
    try:
        annotate_price_changes(db, cards)
        attach_estimates(db, cards)
    except Exception:
        db.rollback()
        logger.warning("scan price annotation failed", exc_info=True)

    return {"data": cards, "page": 1, "pageSize": len(cards), "totalCount": len(cards)}


# ---- Scan accuracy telemetry (roadmap #10) --------------------------------
# Passive labels for measuring real-world scanner accuracy. The frontend already
# knows which candidate the user confirmed (its rank + CLIP score) and the top
# candidate's score, so it reports them here after a successful add — or reports
# the explicit "none of these" gestures (searched away / rescanned) as misses.
# Stored anonymously (no user id): it's aggregate measurement, not per-account
# data. Login-gated + rate-limited via the router deps as an anti-spam guard, but
# the caller's identity is deliberately never persisted.


class ScanFeedbackEvent(BaseModel):
    outcome: Literal["confirmed", "searched_away", "rescanned"]
    candidate_count: int = Field(ge=0)
    picked_rank: int | None = Field(default=None, ge=0)
    picked_score: float | None = None
    top_score: float | None = None
    top_card_id: str | None = Field(default=None, max_length=128)
    picked_card_id: str | None = Field(default=None, max_length=128)


class ScanFeedbackBody(BaseModel):
    # A batch commit reports one event per queued card; a single-mode add or a
    # miss reports one. Cap the list so a bad client can't bulk-insert.
    events: list[ScanFeedbackEvent] = Field(min_length=1, max_length=200)


@router.post("/scan/feedback")
def scan_feedback(body: ScanFeedbackBody, db: Session = Depends(get_db)):
    for e in body.events:
        db.add(ScanFeedback(
            outcome=e.outcome,
            picked_rank=e.picked_rank,
            picked_score=e.picked_score,
            top_score=e.top_score,
            candidate_count=e.candidate_count,
            top_card_id=e.top_card_id,
            picked_card_id=e.picked_card_id,
        ))
    db.commit()
    return {"recorded": len(body.events)}
