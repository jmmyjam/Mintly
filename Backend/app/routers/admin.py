"""Admin-only site stats — the numbers that are annoying to dig out with psql.

Access is gated by app/services/admin_access.py (the ADMIN_EMAILS env var).
Non-admins get the same 404 an unknown path would, so probing the URL reveals
nothing. Everything here is read-only aggregate queries over the app's own
tables — no upstream calls, nothing mutated.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    CardPriceSnapshot,
    CatalogCard,
    CatalogMeta,
    Portfolio,
    PortfolioCard,
    User,
    utcnow,
)
from app.routers.auth import get_current_user
from app.services import card_catalog
from app.services.admin_access import is_admin
from app.services.rate_limit import rate_limit

router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(rate_limit("api", times=120, seconds=60))],
)

SIGNUP_CHART_DAYS = 30
RECENT_USERS = 10


def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    # 404, not 403 — a non-admin probing the path learns nothing
    if not is_admin(current_user):
        raise HTTPException(status_code=404, detail="Not Found")
    return current_user


@router.get("/stats")
def admin_stats(admin: User = Depends(get_admin_user),
                db: Session = Depends(get_db)):
    now = utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # ----- Users -------------------------------------------------------------
    total_users = db.query(func.count(User.id)).scalar() or 0
    new_7d = (
        db.query(func.count(User.id))
        .filter(User.created_at >= now - timedelta(days=7))
        .scalar()
        or 0
    )
    new_30d = (
        db.query(func.count(User.id))
        .filter(User.created_at >= now - timedelta(days=30))
        .scalar()
        or 0
    )
    with_portfolio = (
        db.query(func.count(func.distinct(PortfolioCard.user_id))).scalar() or 0
    )

    # Signups per UTC day over the chart window, zero-filled so the chart shows
    # quiet days as gaps at zero instead of skipping them. func.date returns a
    # date on Postgres and a "YYYY-MM-DD" string on SQLite — str() covers both.
    window_start = today - timedelta(days=SIGNUP_CHART_DAYS - 1)
    signup_rows = (
        db.query(func.date(User.created_at), func.count(User.id))
        .filter(User.created_at >= window_start)
        .group_by(func.date(User.created_at))
        .all()
    )
    counts = {str(day)[:10]: n for day, n in signup_rows}
    signups_by_day = []
    for i in range(SIGNUP_CHART_DAYS):
        date = (window_start + timedelta(days=i)).date().isoformat()
        signups_by_day.append({"date": date, "count": counts.get(date, 0)})

    # ----- Recent signups ----------------------------------------------------
    recent = (
        db.query(User).order_by(User.created_at.desc(), User.id.desc())
        .limit(RECENT_USERS).all()
    )
    lot_counts = dict(
        db.query(PortfolioCard.user_id, func.count(PortfolioCard.id))
        .filter(PortfolioCard.user_id.in_([u.id for u in recent]))
        .group_by(PortfolioCard.user_id)
        .all()
    ) if recent else {}
    recent_users = [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "created_at": u.created_at,
            "lots": lot_counts.get(u.id, 0),
        }
        for u in recent
    ]

    # ----- Portfolios --------------------------------------------------------
    total_lots, distinct_cards, total_quantity = db.query(
        func.count(PortfolioCard.id),
        func.count(func.distinct(PortfolioCard.card_id)),
        func.coalesce(func.sum(PortfolioCard.quantity), 0),
    ).one()
    total_portfolios = db.query(func.count(Portfolio.id)).scalar() or 0

    # ----- Catalog & price history -------------------------------------------
    catalog_cards = db.query(func.count(CatalogCard.card_id)).scalar() or 0
    stale_prices = (
        db.query(func.count(CatalogCard.card_id))
        .filter(CatalogCard.price_updated_at < now - card_catalog.PRICE_TTL)
        .scalar()
        or 0
    )
    sync_row = db.get(CatalogMeta, "last_full_sync")
    snapshot_rows = db.query(func.count(CardPriceSnapshot.id)).scalar() or 0
    # Headline rows only — variant rows would overcount cards priced today
    snapshots_today = (
        db.query(func.count(CardPriceSnapshot.id))
        .filter(CardPriceSnapshot.variant == "",
                CardPriceSnapshot.snapshot_date >= today)
        .scalar()
        or 0
    )
    latest_snapshot = db.query(func.max(CardPriceSnapshot.snapshot_date)).scalar()

    # Postgres-only nicety; SQLite (tests) has no pg_database_size. Last so the
    # rollback can't discard anything, best-effort like the catalog reads.
    try:
        db_size_bytes = db.execute(
            text("SELECT pg_database_size(current_database())")
        ).scalar()
    except Exception:
        db.rollback()
        db_size_bytes = None

    return {
        "generated_at": now,
        "users": {
            "total": total_users,
            "new_7d": new_7d,
            "new_30d": new_30d,
            "with_portfolio": with_portfolio,
        },
        "signups_by_day": signups_by_day,
        "recent_users": recent_users,
        "portfolio": {
            "portfolios": total_portfolios,
            "lots": total_lots,
            "distinct_cards": distinct_cards,
            "total_quantity": int(total_quantity),
        },
        "catalog": {
            "cards": catalog_cards,
            "stale_prices": stale_prices,
            "last_full_sync": sync_row.value if sync_row else None,
        },
        "snapshots": {
            "rows": snapshot_rows,
            "today": snapshots_today,
            "latest": latest_snapshot,
        },
        "db_size_bytes": db_size_bytes,
    }
