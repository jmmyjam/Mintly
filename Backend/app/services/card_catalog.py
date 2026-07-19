"""Local card catalog over `card_catalog` — the upstream card list mirrored
into the DB so browsing is served in milliseconds instead of a 2-5s upstream
call (and keeps working when pokemontcg.io is down).

Filled by the daily crawl (scripts/snapshot_all.py) and topped up whenever the
cards router falls back to the upstream proxy. List queries are only served
from the catalog once a complete crawl has stamped the `last_full_sync` marker
(`is_synced`) — before that, a partially filled catalog would confidently
return incomplete search pages. Single-card lookups are always safe: one row
is one whole card.
"""
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CatalogCard, CatalogMeta, utcnow

PAGE_SIZE = 50  # same paged envelope as the upstream proxy path

# A viewed card whose stored price is older than this gets a background
# re-fetch from upstream (matches the old response cache's 6h freshness)
PRICE_TTL = timedelta(hours=6)

# Only the fields the frontend uses — mirrors _CARD_FIELDS in the cards
# router, so catalog hits and proxy fallbacks serve the same shape
_KEEP = ("id", "name", "number", "rarity", "artist", "hp", "types", "images",
         "set", "tcgplayer")

_SYNC_KEY = "last_full_sync"


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def upsert_cards(db: Session, cards: list[dict], commit: bool = True) -> int:
    """Insert or update catalog rows from upstream card dicts; returns how many
    were written. Stamps price_updated_at — callers only pass freshly fetched
    upstream data, never catalog reads."""
    now = utcnow()
    by_id = {c["id"]: c for c in cards if c.get("id")}
    if not by_id:
        return 0
    existing = {
        r.card_id: r
        for r in db.query(CatalogCard).filter(CatalogCard.card_id.in_(by_id))
    }
    for card_id, card in by_id.items():
        row = existing.get(card_id)
        if row is None:
            row = CatalogCard(card_id=card_id)
            db.add(row)
        card_set = card.get("set") or {}
        types = card.get("types") or []
        row.name = card.get("name")
        row.number = card.get("number")
        row.set_id = card_set.get("id")
        row.rarity = card.get("rarity")
        row.types = f"|{'|'.join(types)}|" if types else None
        row.release_date = card_set.get("releaseDate")
        row.data = {k: card[k] for k in _KEEP if k in card}
        row.price_updated_at = now
    if commit:
        db.commit()
    return len(by_id)


def get_card(db: Session, card_id: str) -> CatalogCard | None:
    return db.get(CatalogCard, card_id)


def card_payload(row: CatalogCard) -> dict:
    # Shallow copy: annotate_price_changes mutates the dict (priceChange), and
    # that must never bleed into the stored JSON
    return dict(row.data)


def price_is_stale(row: CatalogCard) -> bool:
    return row.price_updated_at is None or utcnow() - row.price_updated_at > PRICE_TTL


def search(db: Session, *, name: str | None = None, number: str | None = None,
           set_id: str | None = None, rarity: str | None = None,
           type_: str | None = None, page: int = 1) -> tuple[dict, list[str]]:
    """Paged catalog query. name is a substring match (case-insensitive); the
    rest are exact — same spirit as the upstream filters they replace.
    Returns (envelope in the proxy's shape, ids on this page whose stored
    price is past PRICE_TTL — the router refreshes those in the background)."""
    q = db.query(CatalogCard)
    if name:
        q = q.filter(CatalogCard.name.ilike(f"%{_escape_like(name)}%", escape="\\"))
    if number:
        q = q.filter(CatalogCard.number == number)
    if set_id:
        q = q.filter(CatalogCard.set_id == set_id)
    if rarity:
        q = q.filter(CatalogCard.rarity == rarity)
    if type_:
        q = q.filter(CatalogCard.types.like(f"%|{_escape_like(type_)}|%", escape="\\"))
    total = q.count()
    rows = (
        q.order_by(
            # newest sets first; within a set, natural card-number order
            func.coalesce(CatalogCard.release_date, "").desc(),
            CatalogCard.set_id,
            func.length(CatalogCard.number),
            CatalogCard.number,
            CatalogCard.card_id,
        )
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )
    envelope = {
        "data": [card_payload(r) for r in rows],
        "page": page,
        "pageSize": PAGE_SIZE,
        "totalCount": total,
    }
    return envelope, [r.card_id for r in rows if price_is_stale(r)]


def set_count(db: Session, set_id: str) -> int:
    """How many of a set's cards the catalog holds — checked against the sets
    list's `total` before serving a set page (a half-crawled new set must
    proxy, not serve short pages)."""
    return (
        db.query(func.count(CatalogCard.card_id))
        .filter(CatalogCard.set_id == set_id)
        .scalar()
        or 0
    )


def is_synced(db: Session) -> bool:
    return db.get(CatalogMeta, _SYNC_KEY) is not None


def mark_full_sync(db: Session) -> None:
    row = db.get(CatalogMeta, _SYNC_KEY)
    if row is None:
        row = CatalogMeta(key=_SYNC_KEY)
        db.add(row)
    row.value = utcnow().isoformat()
    db.commit()
