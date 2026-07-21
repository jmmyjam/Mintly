"""Cold storage for old daily price snapshots.

card_price_snapshot grows ~20k rows a day forever if left alone (~1.1GB/year).
Instead of deleting old history, complete months older than the daily window
are exported to gzipped CSV files (one per UTC month) and the DB copy is then
thinned to each card's LAST snapshot of the month — the "monthly close" that
charts keep plotting, stock-market style: daily resolution for the recent
window, monthly beyond it. Nothing is lost: the archive holds every row at
full fidelity and `restore_month` loads a month back into the table.

Safety rules:
- A month is only touched once it is complete AND ended more than
  DAILY_WINDOW_DAYS ago, so the DB always holds at least that much daily data.
- The archive file is written atomically (tmp + rename) BEFORE any deletion;
  rows are only thinned when the month's file exists on disk.
- Idempotent: an existing file is never rewritten (rename means it was written
  whole), and re-thinning an already-thinned month deletes nothing.

The daily snapshot job compacts automatically; `scripts/archive_history.py` is
the manual entry point (compact / list / restore).
"""
import csv
import gzip
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CardPriceSnapshot, utcnow

DAILY_WINDOW_DAYS = 30  # dailies younger than this never leave the DB

_ARCHIVE_DIR = Path(os.getenv(
    "PRICE_ARCHIVE_DIR",
    Path(__file__).resolve().parents[2] / ".archive" / "price-history",
))

_RESTORE_CHUNK = 5000


def month_path(month: str) -> Path:
    return _ARCHIVE_DIR / f"{month}.csv.gz"


def _month_bounds(month: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(month, "%Y-%m")
    if start.month == 12:
        return start, datetime(start.year + 1, 1, 1)
    return start, datetime(start.year, start.month + 1, 1)


def archivable_months(db: Session, today: date | None = None) -> list[str]:
    """Months that are complete and ended more than DAILY_WINDOW_DAYS ago,
    oldest first. Already-compacted months still appear (their close rows keep
    the month non-empty) — compact() handles them cheaply."""
    today = today or utcnow().date()
    cutoff = today - timedelta(days=DAILY_WINDOW_DAYS)
    oldest = db.query(func.min(CardPriceSnapshot.snapshot_date)).scalar()
    if oldest is None:
        return []
    months = []
    cursor = f"{oldest.year:04d}-{oldest.month:02d}"
    while True:
        _, month_end = _month_bounds(cursor)
        if month_end.date() > cutoff:
            return months
        months.append(cursor)
        cursor = f"{month_end.year:04d}-{month_end.month:02d}"


def _month_rows(db: Session, month: str):
    start, end = _month_bounds(month)
    return db.query(CardPriceSnapshot).filter(
        CardPriceSnapshot.snapshot_date >= start,
        CardPriceSnapshot.snapshot_date < end,
    )


def _archive_month(db: Session, month: str) -> int:
    """Write every snapshot row of `month` to its .csv.gz, atomically.
    Returns how many rows were written."""
    path = month_path(month)
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    written = 0
    try:
        with gzip.open(tmp, "wt", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["card_id", "variant", "snapshot_date", "price"])
            query = _month_rows(db, month).order_by(
                CardPriceSnapshot.card_id, CardPriceSnapshot.variant,
                CardPriceSnapshot.snapshot_date)
            for row in query.yield_per(10_000):
                writer.writerow([row.card_id, row.variant,
                                 row.snapshot_date.isoformat(), row.price])
                written += 1
        os.replace(tmp, path)  # the file only ever exists complete
    finally:
        tmp.unlink(missing_ok=True)
    return written


def _thin_month(db: Session, month: str) -> int:
    """Delete the month's rows except each card+variant's last one (the monthly
    close — kept per variant so variant charts get closes too). Only call once
    the month's archive file exists. Returns rows deleted."""
    start, end = _month_bounds(month)
    last = (
        db.query(
            CardPriceSnapshot.card_id,
            CardPriceSnapshot.variant,
            func.max(CardPriceSnapshot.snapshot_date).label("last_date"),
        )
        .filter(
            CardPriceSnapshot.snapshot_date >= start,
            CardPriceSnapshot.snapshot_date < end,
        )
        .group_by(CardPriceSnapshot.card_id, CardPriceSnapshot.variant)
        .subquery()
    )
    keep_ids = db.query(CardPriceSnapshot.id).join(
        last,
        (CardPriceSnapshot.card_id == last.c.card_id)
        & (CardPriceSnapshot.variant == last.c.variant)
        & (CardPriceSnapshot.snapshot_date == last.c.last_date),
    )
    deleted = (
        _month_rows(db, month)
        .filter(~CardPriceSnapshot.id.in_(keep_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def compact(db: Session, today: date | None = None) -> list[dict]:
    """Archive + thin every eligible month. Returns one summary dict per month
    that actually changed something; months already fully compacted are silent."""
    results = []
    for month in archivable_months(db, today):
        path = month_path(month)
        if path.exists():
            archived = 0  # complete by construction (atomic rename) — never rewrite
        else:
            if not db.query(_month_rows(db, month).exists()).scalar():
                continue  # gap month, nothing to do
            archived = _archive_month(db, month)
        deleted = _thin_month(db, month)
        if archived or deleted:
            results.append({
                "month": month,
                "rows_archived": archived,
                "rows_deleted": deleted,
                "path": str(path),
            })
    return results


def restore_month(db: Session, month: str) -> int:
    """Load a month's archived rows back into the table, skipping any that are
    already there. Returns how many rows were added."""
    path = month_path(month)
    if not path.exists():
        raise FileNotFoundError(f"no archive for {month} at {path}")
    existing = {(r.card_id, r.variant, r.snapshot_date) for r in _month_rows(db, month)}
    added = 0
    batch: list[CardPriceSnapshot] = []
    with gzip.open(path, "rt", newline="") as fh:
        for row in csv.DictReader(fh):
            when = datetime.fromisoformat(row["snapshot_date"])
            # archives written before variant tracking have no variant column —
            # every row in them is a headline snapshot
            variant = row.get("variant") or ""
            if (row["card_id"], variant, when) in existing:
                continue
            batch.append(CardPriceSnapshot(
                card_id=row["card_id"], variant=variant,
                price=float(row["price"]), snapshot_date=when))
            added += 1
            if len(batch) >= _RESTORE_CHUNK:
                db.add_all(batch)
                db.commit()
                batch = []
    if batch:
        db.add_all(batch)
        db.commit()
    return added
