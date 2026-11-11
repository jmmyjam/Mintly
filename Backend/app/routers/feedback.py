"""Public feedback form: `POST /feedback`, open to signed-out visitors.

Because anyone can post, spam resistance is layered, cheapest check first:

1. Per-IP rate limits (3 per 10 min, 10 per day).
2. A global cap of GLOBAL_DAILY_CAP messages per 24h, which an attacker
   rotating IPs can't get around. It also bounds the notification emails.
3. A honeypot field (`website`) that real users never see, and a minimum
   time-on-form (`elapsed_ms`, reported by the page). Tripping either gets the
   normal success response with nothing stored, so a bot learns nothing.
4. Content limits: length bounds and at most MAX_LINKS links, since link drops
   are the usual payload of form spam.
5. A repeat of a message already received in the last 24h is silently ignored.

Each accepted message is stored (the Admin page lists it) and emailed to
FEEDBACK_EMAIL best-effort; a mail failure never fails the submission.
"""

import logging
import os
import re
from datetime import timedelta

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Feedback, utcnow
from app.routers.auth import valid_email
from app.services import mailer
from app.services.rate_limit import rate_limit

load_dotenv()

logger = logging.getLogger(__name__)

FEEDBACK_EMAIL = os.getenv("FEEDBACK_EMAIL", "mintlytcg@gmail.com")
GLOBAL_DAILY_CAP = 50
MIN_FILL_MS = 3000
MAX_LINKS = 3
_LINK = re.compile(r"https?://|www\.", re.IGNORECASE)

SUCCESS = {"message": "Thanks! Your feedback was sent."}

router = APIRouter(
    dependencies=[
        Depends(rate_limit("feedback", times=3, seconds=600, what="feedback messages")),
        Depends(rate_limit("feedback-day", times=10, seconds=86400, what="feedback messages")),
    ],
)


class FeedbackBody(BaseModel):
    message: str = Field(max_length=2000)
    email: str | None = Field(default=None, max_length=254)
    page: str | None = Field(default=None, max_length=200)
    # Honeypot: hidden from people, so anything in it came from a bot
    website: str | None = Field(default=None, max_length=200)
    elapsed_ms: int | None = None


def _normalize(message: str) -> str:
    return " ".join(message.lower().split())


def _notify(message: str, email: str | None, page: str | None) -> None:
    body = (f"New feedback on Mintly\n\nFrom: {email or '(no reply address)'}\n"
            f"Page: {page or '(unknown)'}\n\n{message}\n")
    try:
        mailer.send_email(FEEDBACK_EMAIL, "Mintly feedback", body)
    except Exception:
        logger.warning("feedback notification email failed", exc_info=True)


@router.post("/feedback")
def submit_feedback(body: FeedbackBody, background: BackgroundTasks,
                    db: Session = Depends(get_db)):
    message = body.message.strip()
    if len(message) < 10:
        raise HTTPException(status_code=422, detail="Please write at least 10 characters.")
    if len(_LINK.findall(message)) > MAX_LINKS:
        raise HTTPException(status_code=422,
                            detail=f"Please include at most {MAX_LINKS} links.")
    email = (body.email or "").strip() or None
    if email and not valid_email(email):
        raise HTTPException(status_code=422, detail="That email address doesn't look right.")

    if body.website or body.elapsed_ms is None or body.elapsed_ms < MIN_FILL_MS:
        return SUCCESS

    recent = (
        db.query(Feedback.message)
        .filter(Feedback.created_at >= utcnow() - timedelta(hours=24))
        .all()
    )
    if len(recent) >= GLOBAL_DAILY_CAP:
        raise HTTPException(status_code=429,
                            detail="Feedback is busy right now. Please try again later.")
    normalized = _normalize(message)
    if any(_normalize(m) == normalized for (m,) in recent):
        return SUCCESS

    page = (body.page or "").strip() or None
    db.add(Feedback(message=message, email=email, page=page))
    db.commit()
    if FEEDBACK_EMAIL:
        background.add_task(_notify, message, email, page)
    return SUCCESS
