"""Daily job: snapshot the market price of every card, so price history is
gap-free instead of only covering cards someone happened to browse.

Pages the full Pokemon TCG card list (requesting only `id,tcgplayer` to keep
each page small), extracts each card's price, and records one snapshot per card
per UTC day. `record_snapshots` dedupes per day, so this is idempotent — running
it more than once a day adds nothing. Talks straight to the DB and upstream API;
the FastAPI app does not need to be running.

    venv/bin/python snapshot_all.py               # all cards
    venv/bin/python snapshot_all.py --max-pages 2 # smoke test (first 500 cards)

Scheduled daily via launchd (see run_daily_snapshot.sh / the LaunchAgent plist).
"""
import argparse
import logging
import os
import sys
import time

import certifi
import requests
from dotenv import load_dotenv

from database import SessionLocal
from price_history import extract_price, record_snapshots

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("snapshot_all")

BASE_URL = "https://api.pokemontcg.io/v2"
API_KEY = os.getenv("POKEMON_TCG_API_KEY")
_TIMEOUT = (5, 60)          # match the app: 5s connect, 60s read
_PAGE_SIZE = 250            # upstream max
_PAGE_PAUSE = 0.5          # be gentle on the upstream API between pages
_DEDUPE_CHUNK = 1000       # keep the per-day dedupe IN() clause reasonable

session = requests.Session()
session.verify = certifi.where()
session.headers.update({"X-Api-Key": API_KEY})


def _get_page(page: int) -> dict | None:
    """One page of id+price, with a single retry on transient upstream failure."""
    params = {"select": "id,tcgplayer", "page": page, "pageSize": _PAGE_SIZE}
    for attempt in range(2):
        try:
            resp = session.get(f"{BASE_URL}/cards", params=params, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            log.warning("page %d request error (%s)%s", page, exc,
                        " — retrying" if attempt == 0 else " — giving up")
            time.sleep(3)
            continue
        if resp.status_code == 200:
            return resp.json()
        log.warning("page %d HTTP %d%s", page, resp.status_code,
                    " — retrying" if attempt == 0 else " — giving up")
        time.sleep(3)
    return None


def fetch_all_prices(max_pages: int = 0) -> tuple[dict[str, float], bool]:
    """Every card's current price, keyed by card id. Returns (prices, complete)
    where complete is False if any page failed (so we never treat a partial
    crawl as authoritative)."""
    prices: dict[str, float] = {}
    complete = True
    page = 1
    while True:
        payload = _get_page(page)
        if payload is None:
            complete = False
            break
        data = payload.get("data", [])
        if not data:
            break
        for card in data:
            price = extract_price(card)
            if price is not None:
                prices[card["id"]] = price
        total = payload.get("totalCount", 0)
        log.info("page %d: %d cards, %d priced so far / %d total",
                 page, len(data), len(prices), total)
        if page * _PAGE_SIZE >= total or (max_pages and page >= max_pages):
            break
        page += 1
        time.sleep(_PAGE_PAUSE)
    return prices, complete


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot every card's price for history.")
    parser.add_argument("--max-pages", type=int, default=0,
                        help="stop after N pages (0 = all); for smoke tests")
    args = parser.parse_args()

    started = time.time()
    prices, complete = fetch_all_prices(args.max_pages)
    if not prices:
        log.error("fetched no prices — leaving history untouched")
        return 1
    if not complete:
        log.warning("crawl was incomplete (an upstream page failed); recording "
                    "what was fetched — missing cards get caught next run")

    db = SessionLocal()
    try:
        recorded = 0
        items = list(prices.items())
        for i in range(0, len(items), _DEDUPE_CHUNK):
            recorded += record_snapshots(db, dict(items[i:i + _DEDUPE_CHUNK]))
    finally:
        db.close()

    log.info("done in %.0fs — %d cards priced, %d new snapshots recorded today",
             time.time() - started, len(prices), recorded)
    return 0


if __name__ == "__main__":
    sys.exit(main())
