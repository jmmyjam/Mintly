"""Watchlist CRUD — cards a user tracks (and optionally sets a price alert on)
without owning them. One row per (user, card); the alert config (target price +
direction) lives on the row and is evaluated by the daily job
(`app/services/watchlist_alerts.py`).

Prices, day-over-day change, and images are resolved through the exact same
freshest-first pipeline the portfolio uses (`portfolio.fetch_prices` +
`price_history.change_baselines`), so a watched card shows the same value and
daily-change chip the browse/portfolio pages do — including synthetic stamp/mark
variety ids, which `fetch_prices` prices from the catalog/snapshot fallback.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import WatchlistItem
from app.routers import portfolio as portfolio_router
from app.routers.auth import get_current_user
from app.services import card_catalog, tcgcsv
from app.services.price_history import (
    change_baselines, price_change, record_snapshots,
)
from app.services.rate_limit import rate_limit
from app.services.watchlist_alerts import is_triggered

import certifi
import os
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.pokemontcg.io/v2"
API_KEY = os.getenv("POKEMON_TCG_API_KEY")
_TIMEOUT = (5, 60)

_session = requests.Session()
_session.verify = certifi.where()
_session.headers.update({"X-Api-Key": API_KEY})

# Same shared "api" per-IP budget as the cards/portfolio routers (120/min).
router = APIRouter(dependencies=[Depends(rate_limit("api", times=120, seconds=60))])


# ----- Request models --------------------------------------------------------

class AddWatchRequest(BaseModel):
    card_id: str
    # None = watch only (no alert). When set, the daily job emails on a crossing.
    target_price: float | None = Field(None, ge=0)
    direction: Literal["below", "above"] = "below"


# A PATCH replaces the whole alert config (the frontend edit form always submits
# both fields), so it's the same shape as the add body minus the card id.
class UpdateWatchRequest(BaseModel):
    target_price: float | None = Field(None, ge=0)
    direction: Literal["below", "above"] = "below"


# ----- Helpers ----------------------------------------------------------------

def _resolve_card_name(db: Session, card_id: str) -> str:
    """The card's display name, catalog-first (no upstream call when we already
    hold the card), falling back to the upstream single-card lookup for a real
    id the catalog hasn't crawled yet. A synthetic variety id lives only in the
    catalog, so a catalog miss on one is a 404."""
    row = card_catalog.get_card(db, card_id)
    if row is not None:
        return card_catalog.card_payload(row).get("name", "Unknown")
    if tcgcsv.is_variety_id(card_id):
        raise HTTPException(status_code=404, detail="Card not found")
    try:
        response = _session.get(f"{BASE_URL}/cards/{card_id}", timeout=_TIMEOUT)
    except requests.RequestException:
        raise HTTPException(status_code=504, detail="Card lookup timed out. Please try again.")
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Card not found")
    return response.json().get("data", {}).get("name", "Unknown")


def _serialize(item: WatchlistItem, current_price, change, image) -> dict:
    triggered = (
        item.target_price is not None and current_price is not None
        and is_triggered(item.direction, current_price, item.target_price)
    )
    return {
        "id": item.id,
        "card_id": item.card_id,
        "card_name": item.card_name,
        "target_price": item.target_price,
        "direction": item.direction,
        "created_at": item.created_at,
        "current_price": current_price,
        "price_change": change,
        "image_url": image,
        "triggered": triggered,
    }


# ----- Routes ----------------------------------------------------------------

@router.get("/watchlist")
def get_watchlist(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """The user's watched cards (newest first), each priced with its daily-change
    chip and image — the same figures the portfolio/browse pages show."""
    items = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.user_id == current_user.id)
        .order_by(WatchlistItem.created_at.desc(), WatchlistItem.id.desc())
        .all()
    )
    if not items:
        return []
    prices, images = portfolio_router.fetch_prices([i.card_id for i in items], db)
    record_snapshots(db, prices)  # keep watched-but-unbrowsed cards' history warm
    prev = change_baselines(db, prices)

    result = []
    for item in items:
        current_price = prices.get(item.card_id)
        change = None
        if current_price is not None and item.card_id in prev:
            prev_price, since = prev[item.card_id]
            change = price_change(current_price, prev_price, since)
        result.append(_serialize(item, current_price, change, images.get(item.card_id)))
    return result


@router.post("/watchlist")
def add_watch(body: AddWatchRequest, current_user=Depends(get_current_user),
              db: Session = Depends(get_db)):
    """Add a card to the watchlist, or update its alert if already watched
    (idempotent — the unique (user, card) means "add" is really an upsert). A
    changed target/direction re-arms the alert latch so it can fire fresh."""
    card_name = _resolve_card_name(db, body.card_id)
    existing = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.user_id == current_user.id,
                WatchlistItem.card_id == body.card_id)
        .first()
    )
    if existing is not None:
        changed = (existing.target_price != body.target_price
                   or existing.direction != body.direction)
        existing.target_price = body.target_price
        existing.direction = body.direction
        existing.card_name = card_name
        if changed:
            existing.last_alerted_at = None  # re-arm on any alert-config change
        db.commit()
        return {"message": "Watchlist updated", "id": existing.id}

    item = WatchlistItem(
        user_id=current_user.id,
        card_id=body.card_id,
        card_name=card_name,
        target_price=body.target_price,
        direction=body.direction,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"message": "Added to watchlist", "id": item.id}


@router.patch("/watchlist/{item_id}")
def update_watch(item_id: int, body: UpdateWatchRequest,
                 current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.id == item_id, WatchlistItem.user_id == current_user.id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    changed = (item.target_price != body.target_price
               or item.direction != body.direction)
    item.target_price = body.target_price
    item.direction = body.direction
    if changed:
        item.last_alerted_at = None  # a moved threshold should evaluate fresh
    db.commit()
    return {"message": "Watchlist updated"}


@router.delete("/watchlist/{item_id}")
def remove_watch(item_id: int, current_user=Depends(get_current_user),
                 db: Session = Depends(get_db)):
    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.id == item_id, WatchlistItem.user_id == current_user.id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    db.delete(item)
    db.commit()
    return {"message": "Removed from watchlist"}
