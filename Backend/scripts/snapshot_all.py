"""Daily job: snapshot the market price of every card, so price history is
gap-free instead of only covering cards someone happened to browse.

Pages the full Pokemon TCG card list (requesting only `id,tcgplayer` to keep
each page small), extracts each card's price, and records one snapshot per card
per UTC day. `record_snapshots` dedupes per day, so this is idempotent — running
it more than once a day adds nothing. Talks straight to the DB and upstream API;
the FastAPI app does not need to be running.

    venv/bin/python scripts/snapshot_all.py               # all cards
    venv/bin/python scripts/snapshot_all.py --max-pages 2 # smoke test (first 500 cards)

Scheduled daily via launchd (see HANDOFF "Daily snapshot job" / the LaunchAgent plist).
"""
import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass, field

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
    format="%(asctime)s %(levelname).1s %(message)s",  # single-letter level keeps lines scannable
    datefmt="%Y-%m-%d %H:%M:%S",
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
_RETRY_PASS_PAUSE = 30     # cool-down before re-trying failed pages at the end

session = requests.Session()
session.verify = certifi.where()
session.headers.update({"X-Api-Key": API_KEY})


@dataclass
class Crawl:
    """What fetch_all_prices saw: prices plus the page-level story for the summary."""
    prices: dict[str, float] = field(default_factory=dict)
    total_pages: int = 0
    recovered: list[int] = field(default_factory=list)  # failed the sweep, saved by the retry pass
    dropped: list[int] = field(default_factory=list)    # failed both passes

    @property
    def complete(self) -> bool:
        return not self.dropped


def _get_page(page: int) -> dict | None:
    """One page of id+price, retried a few times — upstream flakes with transient
    404s and timeouts. Returns None only after every attempt fails."""
    params = {"select": "id,tcgplayer", "page": page, "pageSize": _PAGE_SIZE}
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = session.get(f"{BASE_URL}/cards", params=params, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            log.warning("  · page %d attempt %d/%d: %s",
                        page, attempt, _MAX_RETRIES, exc)
        else:
            if resp.status_code == 200:
                return resp.json()
            log.warning("  · page %d attempt %d/%d: HTTP %d",
                        page, attempt, _MAX_RETRIES, resp.status_code)
        if attempt < _MAX_RETRIES:
            time.sleep(2 * attempt)  # simple backoff
    return None


def _collect(payload: dict, prices: dict[str, float]) -> None:
    for card in payload.get("data", []):
        price = extract_price(card)
        if price is not None:
            prices[card["id"]] = price


def fetch_all_prices(max_pages: int = 0) -> Crawl:
    """Every card's current price, keyed by card id. A transient failure on one
    page never aborts the crawl (the upstream flakes often enough that one bad
    page shouldn't cost the other ~80): failed pages are remembered and re-tried
    in a second pass at the end, when the flake has usually passed; a page is
    dropped (crawl incomplete) only after failing BOTH passes."""
    crawl = Crawl()
    first = _get_page(1)
    if first is None:
        return crawl  # couldn't even get page 1 — nothing to record

    _collect(first, crawl.prices)
    total = first.get("totalCount", 0)
    crawl.total_pages = max(1, -(-total // _PAGE_SIZE))  # ceil division
    if max_pages:
        crawl.total_pages = min(crawl.total_pages, max_pages)
    width = len(str(crawl.total_pages))
    log.info("page %*d/%d  ok      %7s priced   (%s cards total)",
             width, 1, crawl.total_pages, f"{len(crawl.prices):,}", f"{total:,}")

    failed: list[int] = []
    for page in range(2, crawl.total_pages + 1):
        time.sleep(_PAGE_PAUSE)
        payload = _get_page(page)
        if payload is None:
            failed.append(page)
            log.warning("page %*d/%d  FAILED — queued for end-of-run retry",
                        width, page, crawl.total_pages)
            continue
        _collect(payload, crawl.prices)
        log.info("page %*d/%d  ok      %7s priced",
                 width, page, crawl.total_pages, f"{len(crawl.prices):,}")

    if failed:
        log.info("---- retry pass: %d page(s) failed the sweep, cooling down %ds ----",
                 len(failed), _RETRY_PASS_PAUSE)
        time.sleep(_RETRY_PASS_PAUSE)
        for page in failed:
            time.sleep(_PAGE_PAUSE)
            payload = _get_page(page)
            if payload is None:
                crawl.dropped.append(page)
                log.warning("page %*d     STILL FAILING — dropped this run",
                            width, page)
                continue
            crawl.recovered.append(page)
            _collect(payload, crawl.prices)
            log.info("page %*d     recovered   %7s priced",
                     width, page, f"{len(crawl.prices):,}")
    return crawl


def _fmt_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot every card's price for history.")
    parser.add_argument("--max-pages", type=int, default=0,
                        help="stop after N pages (0 = all); for smoke tests")
    args = parser.parse_args()

    started = time.time()
    crawl = fetch_all_prices(args.max_pages)
    if not crawl.prices:
        log.error("fetched no prices — leaving history untouched")
        return 1

    db = SessionLocal()
    try:
        recorded = 0
        items = list(crawl.prices.items())
        for i in range(0, len(items), _DEDUPE_CHUNK):
            recorded += record_snapshots(db, dict(items[i:i + _DEDUPE_CHUNK]))
    finally:
        db.close()

    # Summary block: the whole run's story at a glance, without reading the pages
    bar = "=" * 52
    ok_pages = crawl.total_pages - len(crawl.dropped)
    log.info(bar)
    log.info("RUN %s", "COMPLETE" if crawl.complete else "INCOMPLETE !!")
    log.info("  duration          %s", _fmt_duration(time.time() - started))
    log.info("  pages             %d/%d ok  (%d recovered, %d dropped)",
             ok_pages, crawl.total_pages, len(crawl.recovered), len(crawl.dropped))
    log.info("  cards priced      %s", f"{len(crawl.prices):,}")
    log.info("  snapshots today   +%s new", f"{recorded:,}")
    if crawl.dropped:
        log.warning("  dropped pages     %s — their cards get caught next run",
                    ", ".join(map(str, crawl.dropped)))
    log.info(bar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
