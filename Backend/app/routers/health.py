from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)):
    # Uptime-monitor probe: 200 only when the app AND its database answer, so
    # a dead Postgres behind a live process still trips the monitor. No rate
    # limit — a monitor polling every 5 minutes must never see a 429.
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok"}
