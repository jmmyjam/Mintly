"""Daily job: snapshot the market price of every card, so price history is
gap-free instead of only covering cards someone happened to browse.

Pages the full Pokemon TCG card list, extracts each card's TCGPlayer price, and
records one snapshot per card per UTC day. Every crawled card is also mirrored
into the `card_catalog` table the app serves browsing from (a complete crawl
stamps the sync marker that lets list endpoints trust the catalog). Cards with no TCGPlayer price (the
newest sets lag upstream, plus ~1.6k old oddballs) then get a second chance: an
eBay sold-listings estimate (the same estimator CardDetail's fallback uses),
newest sets first, paced (`--ebay-pause`) and capped (`--max-ebay`) so the job
can't hammer eBay.
`record_snapshots` dedupes per day, so this is idempotent — running it more than
once a day adds nothing (a re-run spends its eBay budget on cards the first run
didn't reach). Talks straight to the DB and upstream API; the FastAPI app does
not need to be running.

    venv/bin/python scripts/snapshot_all.py               # all cards
    venv/bin/python scripts/snapshot_all.py --max-pages 2 --max-ebay 0  # smoke test

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
from app.services import card_catalog, ebay_prices, history_archive  # noqa: E402
from app.services.price_history import (  # noqa: E402
    extract_price, record_snapshots, recorded_today,
)

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

# The full frontend field set (mirrors _CARD_FIELDS in app/routers/cards.py):
# the crawl now feeds the card_catalog table too, so browsing is served from
# the DB; set carries the name + releaseDate the eBay pass needs as well
_SELECT = "id,name,number,rarity,artist,hp,types,images,set,tcgplayer"
_EBAY_PAUSE = 5.0          # be gentle on eBay between scrapes (--ebay-pause overrides)
_EBAY_GIVEUP = 5           # consecutive FAILED fetches — blocked or offline, stop
_EBAY_MAX = 2000           # default --max-ebay: above the priceless count, so all get tried

session = requests.Session()
session.verify = certifi.where()
session.headers.update({"X-Api-Key": API_KEY})


@dataclass
class Crawl:
    """What fetch_all_prices saw: prices plus the page-level story for the summary."""
    prices: dict[str, float] = field(default_factory=dict)
    cards: list[dict] = field(default_factory=list)     # every card dict, for the catalog upsert
    unpriced: list[dict] = field(default_factory=list)  # no TCGPlayer price — eBay-fill candidates
    total_pages: int = 0
    recovered: list[int] = field(default_factory=list)  # failed the sweep, saved by the retry pass
    dropped: list[int] = field(default_factory=list)    # failed both passes

    @property
    def complete(self) -> bool:
        return not self.dropped


@dataclass
class EbayFill:
    """What the eBay pass did: filled prices plus the numbers for the summary."""
    prices: dict[str, float] = field(default_factory=dict)
    attempted: int = 0
    eligible: int = 0     # unpriced cards still lacking a snapshot today
    no_sales: int = 0     # fetched fine, but too few recent comps to price
    failures: int = 0     # fetches that failed outright (block/network)
    gave_up: bool = False


def _get_page(page: int) -> dict | None:
    """One page of id+price, retried a few times — upstream flakes with transient
    404s and timeouts. Returns None only after every attempt fails."""
    params = {"select": _SELECT, "page": page, "pageSize": _PAGE_SIZE}
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


def _collect(payload: dict, crawl: Crawl) -> None:
    for card in payload.get("data", []):
        crawl.cards.append(card)
        price = extract_price(card)
        if price is not None:
            crawl.prices[card["id"]] = price
        elif card.get("name"):
            card_set = card.get("set") or {}
            crawl.unpriced.append({
                "id": card["id"],
                "name": card["name"],
                "number": card.get("number"),
                "set_name": card_set.get("name"),
                "release": card_set.get("releaseDate") or "",
            })


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

    _collect(first, crawl)
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
        _collect(payload, crawl)
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
            _collect(payload, crawl)
            log.info("page %*d     recovered   %7s priced",
                     width, page, f"{len(crawl.prices):,}")
    return crawl


def _estimate_one(card: dict) -> dict | None:
    """eBay sold-listings summary for one card, or None when the fetch itself
    failed (bot block / network). Callers must treat None differently from a
    fetched-but-saleless summary — only the former suggests we should stop."""
    query = ebay_prices.build_query(card["name"], card["number"], card["set_name"])
    html = ebay_prices._fetch_sold_html(query)
    if html is None:
        return None
    return ebay_prices.summarize(ebay_prices.parse_sold(html), query)


def ebay_fill(db, unpriced: list[dict], budget: int,
              pause: float = _EBAY_PAUSE) -> EbayFill:
    """Second price source for cards TCGPlayer can't price: estimate from recent
    eBay sold listings and snapshot the median (what CardDetail's fallback shows).

    Newest sets first — that's where the TCGPlayer gap actually is; the tail is
    old oddballs, many with too few recent sales to price (those record nothing
    and don't stop the pass — only consecutive failed FETCHES do, since that's
    the bot-block signature). Paced by `pause` seconds per scrape and capped at
    `budget` scrapes per run, skipping cards that already got a snapshot today
    so re-runs spend the budget on new ground.
    """
    fill = EbayFill()
    if budget <= 0 or not unpriced:
        return fill

    done_today: set[str] = set()
    ids = [c["id"] for c in unpriced]
    for i in range(0, len(ids), _DEDUPE_CHUNK):
        done_today |= recorded_today(db, ids[i:i + _DEDUPE_CHUNK])
    todo = sorted((c for c in unpriced if c["id"] not in done_today),
                  key=lambda c: c["release"], reverse=True)
    fill.eligible = len(todo)

    consecutive_failures = 0
    for card in todo[:budget]:
        fill.attempted += 1
        time.sleep(pause)
        try:
            est = _estimate_one(card)
        except Exception as exc:  # scraping shouldn't raise; don't let one card end the run
            log.warning("  ebay %-18s estimator error: %s", card["id"], exc)
            est = None
        if est is None:
            fill.failures += 1
            consecutive_failures += 1
            if consecutive_failures >= _EBAY_GIVEUP:
                fill.gave_up = True
                log.warning("  ebay: %d failed fetches in a row — blocked or "
                            "offline, stopping the eBay pass early",
                            consecutive_failures)
                break
            continue
        consecutive_failures = 0
        if est.get("median"):
            fill.prices[card["id"]] = est["median"]
            log.info("  ebay %-18s $%.2f  (%d sales)",
                     card["id"], est["median"], est.get("count", 0))
        else:
            fill.no_sales += 1
    return fill


def _fmt_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot every card's price for history.")
    parser.add_argument("--max-pages", type=int, default=0,
                        help="stop after N pages (0 = all); for smoke tests")
    parser.add_argument("--max-ebay", type=int, default=_EBAY_MAX,
                        help="cap on eBay sold-listing estimates for cards TCGPlayer "
                             f"can't price (0 = skip the eBay pass; default {_EBAY_MAX} "
                             "— more than the priceless count, so all get tried)")
    parser.add_argument("--ebay-pause", type=float, default=_EBAY_PAUSE,
                        help="seconds to wait between eBay scrapes "
                             f"(default {_EBAY_PAUSE:g})")
    parser.add_argument("--no-compact", action="store_true",
                        help="skip archiving months older than the daily window "
                             "to cold storage")
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

        # Mirror the crawled cards into the local catalog the app browses from.
        # Best-effort: a catalog failure never costs the day's snapshots. The
        # sync marker (which lets list endpoints trust the catalog) is stamped
        # only by a complete, un-truncated crawl — never a --max-pages smoke run.
        upserted = 0
        try:
            for i in range(0, len(crawl.cards), _DEDUPE_CHUNK):
                upserted += card_catalog.upsert_cards(db, crawl.cards[i:i + _DEDUPE_CHUNK])
            if crawl.complete and not args.max_pages:
                card_catalog.mark_full_sync(db)
        except Exception as exc:
            db.rollback()
            log.warning("catalog upsert failed: %s — browsing falls back to the "
                        "upstream proxy until the next run", exc)

        fill = EbayFill()
        if args.max_ebay > 0 and crawl.unpriced:
            log.info("---- eBay fill: %s cards have no TCGPlayer price ----",
                     f"{len(crawl.unpriced):,}")
            fill = ebay_fill(db, crawl.unpriced, args.max_ebay, args.ebay_pause)
            recorded += record_snapshots(db, fill.prices)

        compacted: list[dict] = []
        if not args.no_compact:
            try:
                compacted = history_archive.compact(db)
            except Exception as exc:  # cold storage must never cost us the day's snapshots
                log.warning("history compaction failed: %s — rows stay in the DB "
                            "until the next run", exc)
            for c in compacted:
                log.info("  archived %s: %s rows -> %s  (thinned %s from the DB)",
                         c["month"], f"{c['rows_archived']:,}", c["path"],
                         f"{c['rows_deleted']:,}")
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
    log.info("  catalog           %s cards upserted%s", f"{upserted:,}",
             "" if crawl.complete and not args.max_pages
             else "  (partial run — sync marker untouched)")
    if args.max_ebay > 0:
        log.info("  ebay fill         %d priced of %d tried  (%s eligible, "
                 "%d without recent sales, %d failed fetches)%s",
                 len(fill.prices), fill.attempted, f"{fill.eligible:,}",
                 fill.no_sales, fill.failures,
                 "  — stopped early" if fill.gave_up else "")
    log.info("  snapshots today   +%s new", f"{recorded:,}")
    if compacted:
        log.info("  compacted         %d month(s) to cold storage", len(compacted))
    if crawl.dropped:
        log.warning("  dropped pages     %s — their cards get caught next run",
                    ", ".join(map(str, crawl.dropped)))
    log.info(bar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
