"""Manual entry point for the price-history cold storage (the daily snapshot
job already backs up automatically — this is for inspecting and restoring).

    venv/bin/python scripts/archive_history.py                   # back up old months now
    venv/bin/python scripts/archive_history.py --list            # show archives
    venv/bin/python scripts/archive_history.py --restore 2026-05 # load a month back
"""
import argparse
import os
import sys

from dotenv import load_dotenv

# Run as a plain script, so put Backend/ on the path to import the app package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal  # noqa: E402
from app.services import history_archive  # noqa: E402

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(description="Compact, list, or restore archived price history.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true", help="list archive files")
    group.add_argument("--restore", metavar="YYYY-MM",
                       help="load a month's archived rows back into the DB")
    args = parser.parse_args()

    if args.list:
        files = sorted(history_archive._ARCHIVE_DIR.glob("*.csv.gz"))
        if not files:
            print(f"no archives in {history_archive._ARCHIVE_DIR}")
        for f in files:
            print(f"{f.name}  {f.stat().st_size / 1_048_576:.1f} MB")
        return 0

    db = SessionLocal()
    try:
        if args.restore:
            added = history_archive.restore_month(db, args.restore)
            print(f"restored {args.restore}: {added:,} rows added back")
        else:
            results = history_archive.archive(db)
            if not results:
                print("nothing to back up")
            for r in results:
                print(f"{r['month']}: backed up {r['rows_archived']:,} rows -> {r['path']}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
