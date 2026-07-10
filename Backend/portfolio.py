from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from datetime import datetime, date
import time
import requests
import certifi
import os
from dotenv import load_dotenv

from database import get_db
from models import PortfolioCard, PortfolioSnapshot
from auth import get_current_user

load_dotenv()

BASE_URL = "https://api.pokemontcg.io/v2"
API_KEY = os.getenv("POKEMON_TCG_API_KEY")

_session = requests.Session()
_session.verify = certifi.where()
_session.headers.update({"X-Api-Key": API_KEY})

router = APIRouter()


class AddCardRequest(BaseModel):
    card_id: str
    purchase_price: float | None = Field(None, ge=0)  # None = use current market price
    quantity: int = Field(1, ge=1)


class UpdateCardRequest(BaseModel):
    purchase_price: float | None = Field(None, ge=0)
    quantity: int | None = Field(None, ge=1)


def extract_price(card_data: dict) -> float | None:
    prices = card_data.get("tcgplayer", {}).get("prices", {})
    for price_type in ("holofoil", "normal", "reverseHolofoil", "1stEditionHolofoil"):
        mid = prices.get(price_type, {}).get("mid")
        if mid is not None:
            return mid
    return None


# Prices are cached briefly (15 min) — fresher than the 6h search cache since P&L depends on them.
# Image URLs ride along: card ids alone can't predict them (newer sets live on images.scrydex.com,
# and images.pokemontcg.io serves a card-back PNG for unknown paths).
_price_cache: dict[str, tuple[float, float | None, str | None]] = {}  # (fetched_at, price, image_url)
_PRICE_TTL = 900


def fetch_prices(card_ids: list[str]) -> tuple[dict[str, float], dict[str, str]]:
    now = time.time()
    prices: dict[str, float] = {}
    images: dict[str, str] = {}
    missing: list[str] = []
    for card_id in dict.fromkeys(card_ids):
        cached = _price_cache.get(card_id)
        if cached and now - cached[0] < _PRICE_TTL:
            if cached[1] is not None:
                prices[card_id] = cached[1]
            if cached[2] is not None:
                images[card_id] = cached[2]
        else:
            missing.append(card_id)

    # One upstream call per 100 cards instead of one call per card
    for i in range(0, len(missing), 100):
        chunk = missing[i:i + 100]
        q = " OR ".join(f'id:"{card_id}"' for card_id in chunk)
        response = _session.get(
            f"{BASE_URL}/cards",
            params={"q": q, "select": "id,tcgplayer,images", "pageSize": 250},
        )
        if response.status_code != 200:
            continue
        found = {
            c["id"]: (extract_price(c), c.get("images", {}).get("small"))
            for c in response.json().get("data", [])
        }
        for card_id in chunk:
            price, image = found.get(card_id, (None, None))
            _price_cache[card_id] = (now, price, image)
            if price is not None:
                prices[card_id] = price
            if image is not None:
                images[card_id] = image
    return prices, images


def record_snapshots(db: Session, prices: dict[str, float]):
    # Record at most one snapshot per card per day
    today_start = datetime.combine(date.today(), datetime.min.time())
    already_recorded = {
        s.card_id
        for s in db.query(PortfolioSnapshot).filter(
            PortfolioSnapshot.card_id.in_(prices),
            PortfolioSnapshot.snapshot_date >= today_start,
        )
    }
    new_snapshots = [
        PortfolioSnapshot(card_id=card_id, price=price)
        for card_id, price in prices.items()
        if card_id not in already_recorded
    ]
    if new_snapshots:
        db.add_all(new_snapshots)
        db.commit()


@router.post("/portfolio/add")
def add_card(body: AddCardRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    response = _session.get(f"{BASE_URL}/cards/{body.card_id}")
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Card not found")
    card_data = response.json().get("data", {})
    card_name = card_data.get("name", "Unknown")
    _price_cache[body.card_id] = (time.time(), extract_price(card_data), card_data.get("images", {}).get("small"))

    purchase_price = body.purchase_price
    if purchase_price is None:
        purchase_price = extract_price(card_data)
        if purchase_price is None:
            raise HTTPException(status_code=400, detail="No market price available for this card — enter a purchase price")

    card = PortfolioCard(
        user_id=current_user.id,
        card_id=body.card_id,
        card_name=card_name,
        purchase_price=purchase_price,
        quantity=body.quantity,
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    total = db.query(func.sum(PortfolioCard.quantity)).filter(
        PortfolioCard.user_id == current_user.id,
        PortfolioCard.card_id == body.card_id,
    ).scalar()
    if total > body.quantity:
        return {"message": f"Added — you now have {total} total", "id": card.id}
    return {"message": "Card added", "id": card.id}


@router.get("/portfolio")
def get_portfolio(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    cards = db.query(PortfolioCard).filter(PortfolioCard.user_id == current_user.id).all()

    prices, images = fetch_prices([c.card_id for c in cards])
    record_snapshots(db, prices)

    result = []
    for c in cards:
        current_price = prices.get(c.card_id)
        gain_loss = round((current_price - c.purchase_price) * c.quantity, 2) if current_price is not None else None
        gain_loss_pct = round(((current_price - c.purchase_price) / c.purchase_price) * 100, 2) if current_price and c.purchase_price else None
        result.append({
            "id": c.id,
            "card_id": c.card_id,
            "card_name": c.card_name,
            "quantity": c.quantity,
            "purchase_price": c.purchase_price,
            "purchase_date": c.purchase_date,
            "current_price": current_price,
            "gain_loss": gain_loss,
            "gain_loss_pct": gain_loss_pct,
            "image_url": images.get(c.card_id),
        })
    return result


@router.get("/portfolio/history")
def get_portfolio_history(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    cards = db.query(PortfolioCard).filter(PortfolioCard.user_id == current_user.id).all()
    if not cards:
        return []

    quantities: dict[str, int] = {}
    for c in cards:
        quantities[c.card_id] = quantities.get(c.card_id, 0) + c.quantity

    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.card_id.in_(quantities))
        .order_by(PortfolioSnapshot.snapshot_date)
        .all()
    )

    # One point per day; carry each card's last known price forward so days
    # missing a snapshot for some cards still get a full portfolio total
    by_day: dict[date, dict[str, float]] = {}
    for s in snapshots:
        by_day.setdefault(s.snapshot_date.date(), {})[s.card_id] = s.price

    latest_prices: dict[str, float] = {}
    history = []
    for day in sorted(by_day):
        latest_prices.update(by_day[day])
        total = sum(price * quantities[card_id] for card_id, price in latest_prices.items())
        history.append({"date": day.isoformat(), "total_value": round(total, 2)})
    return history


@router.patch("/portfolio/{portfolio_card_id}")
def update_card(portfolio_card_id: int, body: UpdateCardRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    card = db.query(PortfolioCard).filter(
        PortfolioCard.id == portfolio_card_id,
        PortfolioCard.user_id == current_user.id,
    ).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found in portfolio")
    if body.purchase_price is not None:
        card.purchase_price = body.purchase_price
    if body.quantity is not None:
        card.quantity = body.quantity
    db.commit()
    return {"message": "Card updated"}


@router.delete("/portfolio/{portfolio_card_id}")
def remove_card(portfolio_card_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    card = db.query(PortfolioCard).filter(
        PortfolioCard.id == portfolio_card_id,
        PortfolioCard.user_id == current_user.id,
    ).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found in portfolio")
    db.delete(card)
    db.commit()
    return {"message": "Card removed"}
