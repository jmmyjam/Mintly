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


def variant_prices(card_data: dict) -> dict[str, float]:
    """Every priced TCGPlayer variant of a card, market falling back to mid —
    the same rule extract_price applies to its single preferred variant."""
    out: dict[str, float] = {}
    for variant, block in (card_data.get("tcgplayer", {}).get("prices") or {}).items():
        if not isinstance(block, dict):
            continue
        price = block.get("market")
        if price is None:
            price = block.get("mid")
        if price is not None:
            out[variant] = price
    return out


def _today_start() -> datetime:
    # snapshot_date is naive UTC; deduping by local date would double-record
    # or skip days near midnight
    return datetime.combine(utcnow().date(), datetime.min.time())


def recorded_today(db: Session, card_ids) -> set[str]:
    """Card ids that already have a headline snapshot for today (UTC)."""
    if not card_ids:
        return set()
    return {
        s.card_id
        for s in db.query(CardPriceSnapshot).filter(
            CardPriceSnapshot.card_id.in_(card_ids),
            CardPriceSnapshot.variant == "",
            CardPriceSnapshot.snapshot_date >= _today_start(),
        )
    }


def record_snapshots(db: Session, prices: dict[str, float], variant: str = "") -> int:
    """Record today's price for each card, at most one row per card per variant
    per UTC day (variant "" — the default — is the headline series every
    existing feature reads). A card already snapshotted today has its price
    refreshed to the latest value seen, so the day's point keeps step with the
    current market price shown to users instead of freezing at the first read of
    the day (e.g. the 1pm daily job). Returns how many rows were newly inserted
    — refreshes aren't counted."""
    if not prices:
        return 0
    existing = {
        s.card_id: s
        for s in db.query(CardPriceSnapshot).filter(
            CardPriceSnapshot.card_id.in_(prices),
            CardPriceSnapshot.variant == variant,
            CardPriceSnapshot.snapshot_date >= _today_start(),
        )
    }
    inserted = 0
    changed = False
    for card_id, price in prices.items():
        row = existing.get(card_id)
        if row is None:
            db.add(CardPriceSnapshot(card_id=card_id, variant=variant, price=price))
            inserted += 1
        elif row.price != price:
            row.price = price
            changed = True
    if inserted or changed:
        db.commit()
    return inserted


def record_variant_snapshots(db: Session, cards: list[dict]) -> int:
    """Record today's per-variant prices for cards with 2+ priced TCGPlayer
    variants. Single-variant cards are skipped — their one variant IS the
    headline series record_snapshots already stores, and duplicating it would
    double the table for most of the catalog. Returns rows newly inserted."""
    by_variant: dict[str, dict[str, float]] = {}
    for card in cards:
        card_id = card.get("id")
        if not card_id:
            continue
        prices = variant_prices(card)
        if len(prices) < 2:
            continue
        for variant, price in prices.items():
            by_variant.setdefault(variant, {})[card_id] = price
    inserted = 0
    for variant, prices in by_variant.items():
        inserted += record_snapshots(db, prices, variant=variant)
    return inserted


def previous_prices(db: Session, card_ids: list[str],
                    before: datetime | None = None) -> dict[str, tuple[float, date]]:
    """Each card's most recent snapshot strictly before `before` — default is
    today's UTC start, i.e. the most recent prior-day snapshot."""
    if not card_ids:
        return {}
    cutoff = before if before is not None else _today_start()
    latest = (
        db.query(
            CardPriceSnapshot.card_id,
            func.max(CardPriceSnapshot.snapshot_date).label("latest_date"),
        )
        .filter(
            CardPriceSnapshot.card_id.in_(card_ids),
            CardPriceSnapshot.variant == "",
            CardPriceSnapshot.snapshot_date < cutoff,
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
        .filter(CardPriceSnapshot.variant == "")
        .all()
    )
    return {r.card_id: (r.price, r.snapshot_date.date()) for r in rows}


def latest_prices(db: Session, card_ids: list[str]) -> dict[str, tuple[float, date]]:
    """Each card's most recent snapshot, today included (unlike previous_prices,
    which is strictly before today — that one anchors day-over-day change)."""
    if not card_ids:
        return {}
    latest = (
        db.query(
            CardPriceSnapshot.card_id,
            func.max(CardPriceSnapshot.snapshot_date).label("latest_date"),
        )
        .filter(
            CardPriceSnapshot.card_id.in_(card_ids),
            CardPriceSnapshot.variant == "",
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
        .filter(CardPriceSnapshot.variant == "")
        .all()
    )
    return {r.card_id: (r.price, r.snapshot_date.date()) for r in rows}


def attach_estimates(db: Session, cards: list[dict]) -> None:
    """For cards TCGPlayer can't price, attach the most recent snapshot as
    `estimate` (in place) — the daily job records eBay sold-medians for exactly
    these cards, so search tiles can show an estimated value instead of nothing
    — plus a `priceChange` vs the snapshot before it, so estimated cards get
    the same daily-change chip as priced ones. Cards with a real market price,
    or no snapshot at all, are left untouched."""
    unpriced = [c["id"] for c in cards if c.get("id") and extract_price(c) is None]
    if not unpriced:
        return
    latest = latest_prices(db, unpriced)
    # Change is measured against the snapshot before each card's LATEST one —
    # the cutoff is per-card-day, not "today", so a card whose newest estimate
    # is from yesterday isn't compared against itself
    by_day: dict[date, list[str]] = {}
    for card_id, (_, when) in latest.items():
        by_day.setdefault(when, []).append(card_id)
    prior: dict[str, tuple[float, date]] = {}
    for day, ids in by_day.items():
        prior.update(previous_prices(
            db, ids, before=datetime.combine(day, datetime.min.time())))
    for card in cards:
        hit = latest.get(card.get("id"))
        if hit:
            price, when = hit
            card["estimate"] = {"value": price, "date": when.isoformat()}
            if card["id"] in prior:
                prev_price, since = prior[card["id"]]
                card["priceChange"] = price_change(price, prev_price, since)


def change_baselines(db: Session, current: dict[str, float],
                     ) -> dict[str, tuple[float, date]]:
    """The comparison point for each card's daily-change chip, given the
    current prices: normally the most recent prior-day snapshot. But a day's
    snapshot is refreshed in place to the last price seen that day, so right
    after a UTC rollover yesterday's close equals the current price for the
    whole stretch of the new day until fresh price data lands (the daily crawl
    runs at 20:00 UTC — only 4h before the boundary) — which would pin every
    chip at a meaningless $0.00 most of the day. When yesterday's close equals
    the current price exactly, step one more day back, so the chip keeps
    showing the most recent real move (`since` carries the older date, so the
    chip stays honest about what it's comparing against)."""
    prev = previous_prices(db, list(current))
    flat = [card_id for card_id, (price, _) in prev.items()
            if price == current.get(card_id)]
    by_day: dict[date, list[str]] = {}
    for card_id in flat:
        by_day.setdefault(prev[card_id][1], []).append(card_id)
    for day, ids in by_day.items():
        older = previous_prices(
            db, ids, before=datetime.combine(day, datetime.min.time()))
        prev.update(older)  # cards with no older day keep the flat baseline
    return prev


def price_change(current: float, prev: float, since: date) -> dict:
    return {
        "amount": round(current - prev, 2),
        "percent": round((current - prev) / prev * 100, 2) if prev else None,
        "since": since.isoformat(),
    }


def annotate_price_changes(db: Session, cards: list[dict]) -> None:
    """Record today's snapshots for priced cards (headline + per-variant) and
    attach `priceChange` (vs each card's daily-change baseline — see
    change_baselines) to the card dicts in place."""
    prices: dict[str, float] = {}
    for card in cards:
        price = extract_price(card)
        if price is not None and card.get("id"):
            prices[card["id"]] = price
    if not prices:
        return
    record_snapshots(db, prices)
    record_variant_snapshots(db, cards)
    prev = change_baselines(db, prices)
    for card in cards:
        card_id = card.get("id")
        if card_id in prices and card_id in prev:
            prev_price, since = prev[card_id]
            card["priceChange"] = price_change(prices[card_id], prev_price, since)


def card_history(db: Session, card_id: str, days: int) -> list[dict]:
    """One headline point per UTC day (the dedupe guarantees it), oldest first."""
    cutoff = _today_start() - timedelta(days=days)
    rows = (
        db.query(CardPriceSnapshot)
        .filter(
            CardPriceSnapshot.card_id == card_id,
            CardPriceSnapshot.variant == "",
            CardPriceSnapshot.snapshot_date >= cutoff,
        )
        .order_by(CardPriceSnapshot.snapshot_date)
        .all()
    )
    return [{"date": r.snapshot_date.date().isoformat(), "price": r.price} for r in rows]


def card_variant_history(db: Session, card_id: str, days: int) -> dict[str, list[dict]]:
    """Per-variant daily points for one card, oldest first — only recorded for
    cards with 2+ priced variants, so most cards return {}."""
    cutoff = _today_start() - timedelta(days=days)
    rows = (
        db.query(CardPriceSnapshot)
        .filter(
            CardPriceSnapshot.card_id == card_id,
            CardPriceSnapshot.variant != "",
            CardPriceSnapshot.snapshot_date >= cutoff,
        )
        .order_by(CardPriceSnapshot.snapshot_date)
        .all()
    )
    series: dict[str, list[dict]] = {}
    for r in rows:
        series.setdefault(r.variant, []).append(
            {"date": r.snapshot_date.date().isoformat(), "price": r.price})
    return series
