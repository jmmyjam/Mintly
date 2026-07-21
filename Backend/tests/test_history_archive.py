"""history_archive: old complete months are exported to gzipped CSV before the
DB copy is thinned to monthly closes — never the other way around — and a month
can be restored from its archive file at full fidelity."""
import csv
import gzip
from datetime import date, datetime

import pytest

from app.models import CardPriceSnapshot
from app.services import history_archive
from conftest import TestingSessionLocal

TODAY = date(2026, 7, 17)  # fixed "today": window reaches back to June 17


@pytest.fixture
def archive_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(history_archive, "_ARCHIVE_DIR", tmp_path)
    return tmp_path


def seed(rows: list[tuple[str, str, float]]) -> None:
    """rows: (card_id, 'YYYY-MM-DDTHH:MM', price)"""
    db = TestingSessionLocal()
    db.add_all(
        CardPriceSnapshot(card_id=c, price=p, snapshot_date=datetime.fromisoformat(d))
        for c, d, p in rows)
    db.commit()
    db.close()


def all_rows() -> list[tuple[str, str, float]]:
    db = TestingSessionLocal()
    try:
        return sorted((r.card_id, r.snapshot_date.isoformat(), r.price)
                      for r in db.query(CardPriceSnapshot))
    finally:
        db.close()


MAY_ROWS = [
    ("a", "2026-05-01T12:00", 1.0),
    ("a", "2026-05-15T12:00", 2.0),
    ("a", "2026-05-31T12:00", 3.0),   # a's monthly close
    ("b", "2026-05-02T12:00", 10.0),
    ("b", "2026-05-20T12:00", 20.0),  # b's monthly close
]
JULY_ROWS = [("a", "2026-07-16T12:00", 4.0)]


def test_archivable_months_only_complete_and_out_of_window():
    # June ended 17 days before TODAY — inside the 30-day window, so not archivable
    seed([("a", "2026-04-30T12:00", 1.0), ("a", "2026-06-30T12:00", 2.0)] + JULY_ROWS)
    db = TestingSessionLocal()
    try:
        assert history_archive.archivable_months(db, TODAY) == ["2026-04", "2026-05"]
    finally:
        db.close()


def test_compact_archives_full_month_then_thins_to_closes(archive_dir):
    seed(MAY_ROWS + JULY_ROWS)
    db = TestingSessionLocal()
    try:
        results = history_archive.compact(db, TODAY)
    finally:
        db.close()

    assert [(r["month"], r["rows_archived"], r["rows_deleted"]) for r in results] \
        == [("2026-05", 5, 3)]
    # the archive holds every May row, at full fidelity
    with gzip.open(archive_dir / "2026-05.csv.gz", "rt") as fh:
        archived = sorted((r["card_id"], r["snapshot_date"], float(r["price"]))
                          for r in csv.DictReader(fh))
    assert archived == sorted((c, datetime.fromisoformat(d).isoformat(), p)
                              for c, d, p in MAY_ROWS)
    # the DB keeps each card's last May row (the close) and everything recent
    assert all_rows() == [
        ("a", "2026-05-31T12:00:00", 3.0),
        ("a", "2026-07-16T12:00:00", 4.0),
        ("b", "2026-05-20T12:00:00", 20.0),
    ]


def test_compact_second_run_changes_nothing(archive_dir):
    seed(MAY_ROWS + JULY_ROWS)
    db = TestingSessionLocal()
    try:
        history_archive.compact(db, TODAY)
        before = all_rows()
        content = (archive_dir / "2026-05.csv.gz").read_bytes()
        results = history_archive.compact(db, TODAY)
    finally:
        db.close()

    assert results == []  # fully-compacted months are silent
    assert all_rows() == before
    assert (archive_dir / "2026-05.csv.gz").read_bytes() == content  # never rewritten


def test_failed_archive_write_never_thins(archive_dir, monkeypatch):
    seed(MAY_ROWS + JULY_ROWS)

    def boom(db, month):
        raise OSError("disk full")

    monkeypatch.setattr(history_archive, "_archive_month", boom)
    db = TestingSessionLocal()
    try:
        with pytest.raises(OSError):
            history_archive.compact(db, TODAY)
    finally:
        db.close()

    assert len(all_rows()) == len(MAY_ROWS) + len(JULY_ROWS)  # nothing deleted
    assert list(archive_dir.iterdir()) == []  # and no half-written file


def test_restore_month_brings_thinned_rows_back(archive_dir):
    seed(MAY_ROWS + JULY_ROWS)
    original = all_rows()
    db = TestingSessionLocal()
    try:
        history_archive.compact(db, TODAY)
        added = history_archive.restore_month(db, "2026-05")
        assert added == 3  # only the thinned rows; closes were still in the DB
        assert all_rows() == original
        assert history_archive.restore_month(db, "2026-05") == 0  # already complete
        with pytest.raises(FileNotFoundError):
            history_archive.restore_month(db, "2026-01")
    finally:
        db.close()


def test_compact_keeps_a_close_per_variant(archive_dir):
    # variant rows (multi-variant cards) each keep their own monthly close, so
    # variant charts get monthly resolution beyond the daily window too
    db = TestingSessionLocal()
    db.add_all([
        CardPriceSnapshot(card_id="a", variant="", price=1.0,
                          snapshot_date=datetime(2026, 5, 1, 12)),
        CardPriceSnapshot(card_id="a", variant="", price=2.0,
                          snapshot_date=datetime(2026, 5, 20, 12)),
        CardPriceSnapshot(card_id="a", variant="reverseHolofoil", price=0.5,
                          snapshot_date=datetime(2026, 5, 1, 12)),
        CardPriceSnapshot(card_id="a", variant="reverseHolofoil", price=0.7,
                          snapshot_date=datetime(2026, 5, 20, 12)),
    ])
    db.commit()
    seed(JULY_ROWS)
    try:
        history_archive.compact(db, TODAY)
        kept = sorted((r.card_id, r.variant, r.price)
                      for r in db.query(CardPriceSnapshot)
                      .filter(CardPriceSnapshot.snapshot_date < datetime(2026, 6, 1)))
        assert kept == [("a", "", 2.0), ("a", "reverseHolofoil", 0.7)]
        # ...and the archive round-trips the variant column
        assert history_archive.restore_month(db, "2026-05") == 2
        restored = db.query(CardPriceSnapshot).filter(
            CardPriceSnapshot.variant == "reverseHolofoil").count()
        assert restored == 2
    finally:
        db.close()


def test_restore_pre_variant_archive(archive_dir):
    # archives written before variant tracking lack the variant column — every
    # row in them is a headline snapshot
    with gzip.open(archive_dir / "2026-05.csv.gz", "wt", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["card_id", "snapshot_date", "price"])
        writer.writerow(["a", "2026-05-01T12:00:00", 1.5])
    db = TestingSessionLocal()
    try:
        assert history_archive.restore_month(db, "2026-05") == 1
        row = db.query(CardPriceSnapshot).one()
        assert (row.card_id, row.variant, row.price) == ("a", "", 1.5)
    finally:
        db.close()
