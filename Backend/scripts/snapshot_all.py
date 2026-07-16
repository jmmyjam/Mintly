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

# Run as a plain script (python scripts/snapshot_all.py), so put Backend/ on the
# path to make the `app` package importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal  # noqa: E402
from app.services.price_history import extract_price, record_snapshots  # noqa: E402

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
_MAX_RETRIES = 3           # upstream flakes with transient 404s/timeouts

session = requests.Session()
session.verify = certifi.where()
session.headers.update({"X-Api-Key": API_KEY})


def _get_page(page: int) -> dict | None:
    """One page of id+price, retried a few times — upstream flakes with transient
    404s and timeouts. Returns None only after every attempt fails."""
    params = {"select": "id,tcgplayer", "page": page, "pageSize": _PAGE_SIZE}
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = session.get(f"{BASE_URL}/cards", params=params, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            log.warning("page %d request error (%s), attempt %d/%d",
                        page, exc, attempt, _MAX_RETRIES)
        else:
            if resp.status_code == 200:
                return resp.json()
            log.warning("page %d HTTP %d, attempt %d/%d",
                        page, resp.status_code, attempt, _MAX_RETRIES)
        if attempt < _MAX_RETRIES:
            time.sleep(2 * attempt)  # simple backoff
    return None


def _collect(payload: dict, prices: dict[str, float]) -> None:
    for card in payload.get("data", []):
        price = extract_price(card)
        if price is not None:
            prices[card["id"]] = price


def fetch_all_prices(max_pages: int = 0) -> tuple[dict[str, float], bool]:
    """Every card's current price, keyed by card id. Returns (prices, complete);
    complete is False if any page had to be skipped. A transient failure on one
    page skips just that page — it never aborts the whole crawl (the upstream
    flakes often enough that one bad page shouldn't cost the other ~80)."""
    first = _get_page(1)
    if first is None:
        return {}, False  # couldn't even get page 1 — nothing to record

    prices: dict[str, float] = {}
    _collect(first, prices)
    total = first.get("totalCount", 0)
    total_pages = max(1, -(-total // _PAGE_SIZE))  # ceil division
    if max_pages:
        total_pages = min(total_pages, max_pages)
    log.info("page 1/%d: %d priced so far / %d total", total_pages, len(prices), total)

    complete = True
    for page in range(2, total_pages + 1):
        time.sleep(_PAGE_PAUSE)
        payload = _get_page(page)
        if payload is None:
            complete = False
            log.warning("page %d/%d skipped after %d attempts — continuing",
                        page, total_pages, _MAX_RETRIES)
            continue
        _collect(payload, prices)
        log.info("page %d/%d: %d priced so far", page, total_pages, len(prices))
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
