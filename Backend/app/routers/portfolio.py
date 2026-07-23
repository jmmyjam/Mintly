from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from datetime import date
import time
import requests
import certifi
import os
from dotenv import load_dotenv

from app.database import get_db
from app.models import PortfolioCard, CardPriceSnapshot
from app.routers.auth import get_current_user
from app.services import card_catalog
from app.services.price_history import (
    extract_price, record_snapshots, change_baselines, price_change, latest_prices,
)
from app.services.rate_limit import rate_limit

load_dotenv()


# ----- Configuration ---------------------------------------------------------

BASE_URL = "https://api.pokemontcg.io/v2"
API_KEY = os.getenv("POKEMON_TCG_API_KEY")

# Prices are cached briefly (15 min) — fresher than the 6h search cache since P&L depends on them.
_PRICE_TTL = 900

# 5s to connect, 60s per read — upstream can be slow but must not hang a worker
_TIMEOUT = (5, 60)


# ----- Global state ----------------------------------------------------------

# Image URLs ride along with prices: card ids alone can't predict them (newer sets
# live on images.scrydex.com, and images.pokemontcg.io serves a card-back PNG for
# unknown paths).
_price_cache: dict[str, tuple[float, float | None, str | None]] = {}  # (fetched_at, price, image_url)

_session = requests.Session()
_session.verify = certifi.where()
_session.headers.update({"X-Api-Key": API_KEY})

# Same "api" scope as the cards router — one shared per-IP budget for the API
router = APIRouter(dependencies=[Depends(rate_limit("api", times=120, seconds=60))])


# ----- Request models --------------------------------------------------------

class AddCardRequest(BaseModel):
    card_id: str
    purchase_price: float | None = Field(None, ge=0)  # None = use current market price
    quantity: int = Field(1, ge=1)


class UpdateCardRequest(BaseModel):
    purchase_price: float | None = Field(None, ge=0)
    quantity: int | None = Field(None, ge=1)


# ----- Helpers ----------------------------------------------------------------

def _fallback_prices(db: Session, card_ids: list[str]) -> tuple[dict[str, float], dict[str, str]]:
    """Prices + images for cards pokemontcg.io returns unpriced, in the app's
    source-accuracy order: the real TCGplayer price the daily job seeded into
    the local catalog from TCGCSV (the newest sets upstream lags on), then the
    latest recorded snapshot — the daily job's eBay sold-median. Returns only
    the cards a source could price (plus any catalog image, snapshot or not)."""
    prices: dict[str, float] = {}
    images: dict[str, str] = {}
    if not card_ids:
        return prices, images
    rows = card_catalog.get_cards(db, card_ids)
    for card_id in card_ids:
        row = rows.get(card_id)
        if row is None:
            continue
        data = row.data or {}
        price = extract_price(data)
        if price is not None:
            prices[card_id] = price
        image = (data.get("images") or {}).get("small")
        if image:
            images[card_id] = image
    remaining = [cid for cid in card_ids if cid not in prices]
    if remaining:
        for card_id, (price, _when) in latest_prices(db, remaining).items():
            prices[card_id] = price
    return prices, images


def fetch_prices(card_ids: list[str], db: Session | None = None) -> tuple[dict[str, float], dict[str, str]]:
    """Current price + image for each card. The freshest source wins: the live
    pokemontcg.io TCGplayer figure, then — for cards it returns unpriced — the
    TCGCSV/eBay fallbacks the daily job records (see `_fallback_prices`), so the
    portfolio tracks value from every source the browsing pages already show."""
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
    if not missing:
        return prices, images

    resolved: dict[str, float] = {}
    resolved_images: dict[str, str] = {}
    reached: set[str] = set()  # cards upstream gave a definitive answer for

    # 1) Live upstream — the freshest TCGplayer market price, one call per 100
    for i in range(0, len(missing), 100):
        chunk = missing[i:i + 100]
        q = " OR ".join(f'id:"{card_id}"' for card_id in chunk)
        try:
            response = _session.get(
                f"{BASE_URL}/cards",
                params={"q": q, "select": "id,tcgplayer,images", "pageSize": 250},
                timeout=_TIMEOUT,
            )
        except requests.RequestException:
            continue  # portfolio still renders; a transient failure retries next load
        if response.status_code != 200:
            continue
        reached.update(chunk)
        for c in response.json().get("data", []):
            card_id = c.get("id")
            if not card_id:
                continue
            price = extract_price(c)
            if price is not None:
                resolved[card_id] = price
            image = c.get("images", {}).get("small")
            if image:
                resolved_images[card_id] = image

    # 2) Fill the cards upstream couldn't price from the catalog (TCGCSV) then
    #    the latest snapshot (eBay median). Upstream stays the source of truth
    #    where it has a price — this only reaches the newest sets it lags on.
    if db is not None:
        gap = [cid for cid in missing if cid not in resolved]
        if gap:
            fb_prices, fb_images = _fallback_prices(db, gap)
            resolved.update(fb_prices)
            for cid, image in fb_images.items():
                resolved_images.setdefault(cid, image)

    for card_id in missing:
        price = resolved.get(card_id)
        image = resolved_images.get(card_id)
        # Cache a definitive upstream answer or any resolved fallback; a card
        # whose upstream chunk failed and that no source could price stays
        # uncached, so a transient upstream error is retried on the next load.
        if card_id in reached or price is not None or image is not None:
            _price_cache[card_id] = (now, price, image)
        if price is not None:
            prices[card_id] = price
        if image is not None:
            images[card_id] = image
    return prices, images


# ----- Routes ----------------------------------------------------------------

@router.post("/portfolio/add")
def add_card(body: AddCardRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        response = _session.get(f"{BASE_URL}/cards/{body.card_id}", timeout=_TIMEOUT)
    except requests.RequestException:
        raise HTTPException(status_code=504, detail="Card lookup timed out — try again")
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Card not found")
    card_data = response.json().get("data", {})
    card_name = card_data.get("name", "Unknown")

    # Current market price: live upstream first, then the TCGCSV/eBay fallbacks
    # for the newest sets upstream returns unpriced. Seed the price cache with
    # the resolved value (not the bare upstream one) so the next /portfolio load
    # doesn't read back a cached None and hide the fallback price.
    market_price = extract_price(card_data)
    if market_price is None:
        market_price = _fallback_prices(db, [body.card_id])[0].get(body.card_id)
    _price_cache[body.card_id] = (time.time(), market_price, card_data.get("images", {}).get("small"))

    purchase_price = body.purchase_price
    if purchase_price is None:
        purchase_price = market_price
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

    prices, images = fetch_prices([c.card_id for c in cards], db)
    record_snapshots(db, prices)
    # Each card's daily-change baseline (the most recent prior-day snapshot,
    # stepping past a close that already equals the current price)
    prev = change_baselines(db, prices)

    result = []
    for c in cards:
        current_price = prices.get(c.card_id)
        gain_loss = round((current_price - c.purchase_price) * c.quantity, 2) if current_price is not None else None
        gain_loss_pct = round(((current_price - c.purchase_price) / c.purchase_price) * 100, 2) if current_price and c.purchase_price else None
        change = None
        if current_price is not None and c.card_id in prev:
            prev_price, since = prev[c.card_id]
            change = price_change(current_price, prev_price, since)
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
            "price_change": change,
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

    # Portfolio value history is derived from the shared card-price snapshots
    # (headline rows only — per-variant rows would overwrite the real price),
    # scoped to the cards this user holds
    snapshots = (
        db.query(CardPriceSnapshot)
        .filter(
            CardPriceSnapshot.card_id.in_(quantities),
            CardPriceSnapshot.variant == "",
        )
        .order_by(CardPriceSnapshot.snapshot_date)
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
