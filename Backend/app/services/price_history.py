"""Per-card daily price history shared by the card and portfolio routers.

card_price_snapshot is the app-wide price-history store: every card that passes
through a card endpoint with a price gets at most one snapshot per UTC day, so
daily changes and per-card history charts work for anything users browse — not
just cards someone holds in a portfolio. Portfolio value-over-time is derived
from the same table (see portfolio.get_portfolio_history).
"""
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CardPriceSnapshot, utcnow


def extract_price(card_data: dict) -> float | None:
    # TCGPlayer's market price tracks actual sales; mid is only a listing
    # midpoint, so it's just the fallback when market is missing
    prices = card_data.get("tcgplayer", {}).get("prices", {})
    for price_type in ("holofoil", "normal", "reverseHolofoil", "1stEditionHolofoil"):
        variant = prices.get(price_type, {})
        price = variant.get("market")
        if price is None:
            price = variant.get("mid")
        if price is not None:
            return price
    return None


def _today_start() -> datetime:
    # snapshot_date is naive UTC; deduping by local date would double-record
    # or skip days near midnight
    return datetime.combine(utcnow().date(), datetime.min.time())


def recorded_today(db: Session, card_ids) -> set[str]:
    """Card ids that already have a snapshot for today (UTC)."""
    if not card_ids:
        return set()
    return {
        s.card_id
        for s in db.query(CardPriceSnapshot).filter(
            CardPriceSnapshot.card_id.in_(card_ids),
            CardPriceSnapshot.snapshot_date >= _today_start(),
        )
    }


def record_snapshots(db: Session, prices: dict[str, float]) -> int:
    # At most one snapshot per card per UTC day; returns how many rows were added
    if not prices:
        return 0
    already_recorded = recorded_today(db, prices)
    new_snapshots = [
        CardPriceSnapshot(card_id=card_id, price=price)
        for card_id, price in prices.items()
        if card_id not in already_recorded
    ]
    if new_snapshots:
        db.add_all(new_snapshots)
        db.commit()
    return len(new_snapshots)


def previous_prices(db: Session, card_ids: list[str]) -> dict[str, tuple[float, date]]:
    """Each card's most recent snapshot strictly before today (UTC)."""
    if not card_ids:
        return {}
    today_start = _today_start()
    latest = (
        db.query(
            CardPriceSnapshot.card_id,
            func.max(CardPriceSnapshot.snapshot_date).label("latest_date"),
        )
        .filter(
            CardPriceSnapshot.card_id.in_(card_ids),
            CardPriceSnapshot.snapshot_date < today_start,
        )
        .group_by(CardPriceSnapshot.card_id)
        .subquery()
    )
    rows = (
        db.query(CardPriceSnapshot)
        .join(
            latest,
            (CardPriceSnapshot.card_id == latest.c.card_id)
            & (CardPriceSnapshot.snapshot_date == latest.c.latest_date),
        )
        .all()
    )
    return {r.card_id: (r.price, r.snapshot_date.date()) for r in rows}


def price_change(current: float, prev: float, since: date) -> dict:
    return {
        "amount": round(current - prev, 2),
        "percent": round((current - prev) / prev * 100, 2) if prev else None,
        "since": since.isoformat(),
    }


def annotate_price_changes(db: Session, cards: list[dict]) -> None:
    """Record today's snapshots for priced cards and attach `priceChange`
    (vs each card's most recent prior snapshot) to the card dicts in place."""
    prices: dict[str, float] = {}
    for card in cards:
        price = extract_price(card)
        if price is not None and card.get("id"):
            prices[card["id"]] = price
    if not prices:
        return
    record_snapshots(db, prices)
    prev = previous_prices(db, list(prices))
    for card in cards:
        card_id = card.get("id")
        if card_id in prices and card_id in prev:
            prev_price, since = prev[card_id]
            card["priceChange"] = price_change(prices[card_id], prev_price, since)


def card_history(db: Session, card_id: str, days: int) -> list[dict]:
    """One point per UTC day (the dedupe guarantees it), oldest first."""
    cutoff = _today_start() - timedelta(days=days)
    rows = (
        db.query(CardPriceSnapshot)
        .filter(
            CardPriceSnapshot.card_id == card_id,
            CardPriceSnapshot.snapshot_date >= cutoff,
        )
        .order_by(CardPriceSnapshot.snapshot_date)
        .all()
    )
    return [{"date": r.snapshot_date.date().isoformat(), "price": r.price} for r in rows]
