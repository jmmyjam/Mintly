"""On-disk backup of old price snapshots.

Every complete month older than ARCHIVE_AFTER_DAYS is exported to a gzipped CSV
(one per UTC month) as a redundant, full-fidelity backup of price history. The
DB keeps every daily row forever — nothing is deleted here — so long-range
charts stay at daily resolution; the CSVs are purely a backup (rsynced off the
box by backup.sh alongside the nightly pg_dump, which already holds the same
rows). `restore_month` loads a month's rows back from its archive, skipping any
already present, so a fresh DB can be rebuilt from the CSVs if a dump is ever
lost.

Safety rules:
- A month is only archived once it is complete AND ended more than
  ARCHIVE_AFTER_DAYS ago.
- The archive file is written atomically (tmp + rename), so it only ever exists
  whole.
- Idempotent: an existing file is never rewritten (rename means it was written
  whole), so re-archiving a month already on disk is a cheap no-op.

The daily snapshot job archives automatically; `scripts/archive_history.py` is
the manual entry point (archive / list / restore).
"""
import csv
import gzip
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CardPriceSnapshot, utcnow

ARCHIVE_AFTER_DAYS = 30  # a month is backed up once it has been complete this long

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
    """Months that are complete and ended more than ARCHIVE_AFTER_DAYS ago,
    oldest first. Already-archived months still appear (their rows never leave
    the DB) — archive() skips them cheaply via the on-disk file check."""
    today = today or utcnow().date()
    cutoff = today - timedelta(days=ARCHIVE_AFTER_DAYS)
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


def archive(db: Session, today: date | None = None) -> list[dict]:
    """Back up every eligible month to its .csv.gz. DB rows are never deleted —
    the archive is a redundant, full-fidelity copy of price history. Returns one
    summary dict per month newly written; months already on disk are silent."""
    results = []
    for month in archivable_months(db, today):
        path = month_path(month)
        if path.exists():
            continue  # already backed up (atomic rename means it is whole)
        if not db.query(_month_rows(db, month).exists()).scalar():
            continue  # gap month, nothing to back up
        written = _archive_month(db, month)
        results.append({
            "month": month,
            "rows_archived": written,
            "path": str(path),
        })
    return results


def restore_month(db: Session, month: str) -> int:
    """Load a month's archived rows back into the table, skipping any that are
    already there. Returns how many rows were added. Nothing is thinned any
    more, so this only adds rows for a DB that has lost them (e.g. a rebuild
    from the CSV backups)."""
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
