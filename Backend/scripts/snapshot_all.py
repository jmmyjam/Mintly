"""Daily job: snapshot the market price of every card, so price history is
gap-free instead of only covering cards someone happened to browse.

Pages the full Pokemon TCG card list, extracts each card's TCGPlayer price, and
records one snapshot per card per UTC day. Cards with no TCGPlayer price (the
newest sets lag upstream, plus ~1.6k old oddballs) get two more chances, in
order of accuracy: first real TCGplayer prices from the TCGCSV nightly mirror
(`tcgcsv_fill` — matched by set + card number, injected into the card dicts so
the catalog stores them like any other TCGplayer price; `--no-tcgcsv` skips),
then an eBay sold-listings estimate for whatever TCGCSV couldn't match (the
same estimator CardDetail's fallback uses), newest sets first, paced
(`--ebay-pause`) and capped (`--max-ebay`) so the job can't hammer eBay.
Cards upstream DOES price are cross-checked against the same TCGCSV mirror
(`price_sanity_check`): a ≥3x divergence on a name-and-number-matched product
means upstream's block maps the wrong product (e.g. a [Staff] promo) or holds
a junk figure, and TCGplayer's own number wins.
Every crawled card is also mirrored into the `card_catalog` table the app
serves browsing from (a complete crawl stamps the sync marker that lets list
endpoints trust the catalog).

Cards on pages pokemontcg.io *couldn't serve at all* (a page that failed both
the inline retries and every end-of-run retry pass — `crawl.dropped`) are a
separate gap from cards it served with no price: they never reach the fills
above. A final `recover_dropped` stage recovers those cards' metadata from the
catalog (any card the catalog holds that this run didn't crawl) and prices them
from the same TCGCSV mirror, so an upstream page outage doesn't punch a hole in
the day's history. It only runs on a full, already-synced run — a brand-new
card the catalog has never seen still waits for the next complete crawl.
`record_snapshots` dedupes per day, so this is idempotent — running it more than
once a day adds nothing (a re-run spends its eBay budget on cards the first run
didn't reach). Talks straight to the DB and upstream API; the FastAPI app does
not need to be running.

    venv/bin/python scripts/snapshot_all.py               # all cards
    venv/bin/python scripts/snapshot_all.py --max-pages 2 --max-ebay 0 --no-tcgcsv  # smoke test

Scheduled daily via launchd (see HANDOFF "Daily snapshot job" / the LaunchAgent plist).
"""
import argparse
import copy
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
from app.models import CatalogCard  # noqa: E402
from app.services import card_catalog, ebay_prices, history_archive, tcgcsv  # noqa: E402
from app.services.price_history import (  # noqa: E402
    extract_price, record_snapshots, record_variant_snapshots, recorded_today,
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
_RETRY_PASSES = 3          # end-of-run sweeps over still-failing pages
_RETRY_PASS_PAUSE = 30     # cool-down before the first sweep; doubles each pass

# The full frontend field set (mirrors _CARD_FIELDS in app/routers/cards.py):
# the crawl now feeds the card_catalog table too, so browsing is served from
# the DB; set carries the name + releaseDate the eBay pass needs as well
_SELECT = "id,name,number,rarity,artist,hp,types,images,set,tcgplayer"
_EBAY_PAUSE = 3.0          # be gentle on eBay between scrapes (--ebay-pause overrides)
_EBAY_GIVEUP = 5           # consecutive FAILED fetches — blocked or offline, stop
_EBAY_MAX = 500           # default --max-ebay: above the priceless count, so all get tried

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
    dropped: list[int] = field(default_factory=list)    # failed every retry pass

    @property
    def complete(self) -> bool:
        return not self.dropped


@dataclass
class TcgcsvFill:
    """What the TCGCSV pass did: real TCGplayer prices injected for cards
    pokemontcg.io couldn't price, plus the numbers for the summary."""
    prices: dict[str, float] = field(default_factory=dict)
    sets_matched: int = 0
    sets_unmatched: list[str] = field(default_factory=list)


@dataclass
class SanityFill:
    """What the price sanity check did: upstream prices replaced with the
    TCGplayer figure from the TCGCSV mirror where the two wildly disagree."""
    replaced: dict[str, float] = field(default_factory=dict)
    sets_checked: int = 0


@dataclass
class EbayFill:
    """What the eBay pass did: filled prices plus the numbers for the summary."""
    prices: dict[str, float] = field(default_factory=dict)
    attempted: int = 0
    eligible: int = 0     # unpriced cards still lacking a snapshot today
    no_sales: int = 0     # fetched fine, but too few recent comps to price
    failures: int = 0     # fetches that failed outright (block/network)
    gave_up: bool = False


@dataclass
class DroppedFill:
    """What the dropped-page recovery did: TCGCSV prices pulled for cards on
    pages pokemontcg.io couldn't serve this run (recovered via the catalog)."""
    prices: dict[str, float] = field(default_factory=dict)
    cards: list[dict] = field(default_factory=list)  # recovered dicts, re-upserted
    candidates: int = 0   # catalog cards this run never crawled (= dropped-page cards)
    sets_matched: int = 0
    sets_unmatched: list[str] = field(default_factory=list)


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
                "set_id": card_set.get("id"),
                "set_name": card_set.get("name"),
                "release": card_set.get("releaseDate") or "",
            })


def fetch_all_prices(max_pages: int = 0) -> Crawl:
    """Every card's current price, keyed by card id. A transient failure on one
    page never aborts the crawl (the upstream flakes often enough that one bad
    page shouldn't cost the other ~80): failed pages are remembered and re-tried
    in up to _RETRY_PASSES end-of-run sweeps with doubling cool-downs, when the
    flake has usually passed; a page is dropped (crawl incomplete) only after
    failing every sweep too."""
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

    # Up to _RETRY_PASSES end-of-run sweeps with doubling cool-downs: a flake
    # burst that outlives one 30s pause rarely outlives three minutes, and a
    # page is only dropped (run incomplete) after failing every sweep too
    cooldown = _RETRY_PASS_PAUSE
    for sweep in range(1, _RETRY_PASSES + 1):
        if not failed:
            break
        log.info("---- retry pass %d/%d: %d page(s) still failing, cooling "
                 "down %ds ----", sweep, _RETRY_PASSES, len(failed), cooldown)
        time.sleep(cooldown)
        cooldown *= 2
        still_failing: list[int] = []
        for page in failed:
            time.sleep(_PAGE_PAUSE)
            payload = _get_page(page)
            if payload is None:
                still_failing.append(page)
                continue
            crawl.recovered.append(page)
            _collect(payload, crawl)
            log.info("page %*d     recovered   %7s priced",
                     width, page, f"{len(crawl.prices):,}")
        failed = still_failing
    for page in failed:
        crawl.dropped.append(page)
        log.warning("page %*d     STILL FAILING — dropped this run", width, page)
    return crawl


def tcgcsv_fill(crawl: Crawl) -> TcgcsvFill:
    """First fallback for cards pokemontcg.io can't price: real TCGplayer
    prices from the TCGCSV nightly mirror, matched by set + card number.

    Matched prices are injected straight into the card dicts in `crawl.cards`
    (as a `tcgplayer.prices` block), so the catalog upsert that follows stores
    them exactly like upstream-priced cards — the app then renders these as
    normally TCGplayer-priced, variant tiles and all. Only cards TCGCSV can't
    match fall through to the eBay pass. Each set's group is fetched once;
    unmatched sets are collected so gaps stay visible in the log.
    """
    fill = TcgcsvFill()
    if not crawl.unpriced:
        return fill

    by_id = {c["id"]: c for c in crawl.cards}
    by_set: dict[tuple, list[dict]] = {}
    for card in crawl.unpriced:
        by_set.setdefault((card.get("set_id"), card.get("set_name")), []).append(card)

    for (set_id, set_name), cards_in_set in sorted(
            by_set.items(), key=lambda kv: kv[0][1] or ""):
        try:
            group_id = tcgcsv.group_id_for_set(set_name, set_id)
            candidates = tcgcsv.candidates_for_group(group_id) if group_id else {}
        except Exception as exc:  # the service is best-effort, but never trust that
            log.warning("  tcgcsv %-24s lookup error: %s", set_name, exc)
            candidates = {}
        if not candidates:
            fill.sets_unmatched.append(set_name or "?")
            continue
        fill.sets_matched += 1
        before = len(fill.prices)
        for card in cards_in_set:
            # The card name picks the right product when several share a
            # number (regular vs [Staff] promos, merged Trainer Kit decks)
            prices = tcgcsv.pick_product(
                candidates.get(tcgcsv.norm_number(card.get("number") or "")),
                card.get("name"))
            full = by_id.get(card["id"])
            if not prices or full is None:
                continue
            price = extract_price({"tcgplayer": {"prices": prices}})
            if price is None:
                continue  # no variant the app reads — leave the card untouched
            # Preserve any existing url/updatedAt alongside the injected prices;
            # the priceSource mark keeps the request-path catalog refresh from
            # overwriting this block with upstream's figure (see upsert_cards)
            block = full.setdefault("tcgplayer", {})
            block["prices"] = prices
            block["priceSource"] = "tcgcsv"
            fill.prices[card["id"]] = price
        log.info("  tcgcsv %-24s %d/%d cards priced",
                 set_name, len(fill.prices) - before, len(cards_in_set))
    if fill.sets_unmatched:
        log.info("  tcgcsv: no match for set(s): %s — those cards fall through "
                 "to the eBay pass", ", ".join(fill.sets_unmatched))
    return fill


# A priced card's upstream figure and TCGplayer's own current figure for the
# same product should be near-identical (upstream mirrors TCGplayer with a few
# days' lag). Divergence past this factor means upstream's block points at the
# wrong product or carries a junk figure — observed live July 23, 2026:
# swshp-SWSH066 served at the [Staff] promo's $580.92 against the regular
# card's $98.49 market, and neo4-107 (Shining Charizard) at a $19.99 outlier
# against a $3,998.99 market.
_SANITY_RATIO = 3.0


def price_sanity_check(crawl: Crawl) -> SanityFill:
    """Cross-check every upstream-priced card against the TCGplayer figure the
    TCGCSV mirror reports for the same set + number + NAME; where they diverge
    by ≥ _SANITY_RATIO, TCGplayer's own data wins: the card dict's prices block
    is replaced (marked priceSource so the request-path refresh can't undo it)
    and crawl.prices corrected, so the snapshot, catalog row, and variant rows
    that follow all record the sane figure. The name match is required — for a
    number several products share, overriding a real price on a number-only
    match would risk pricing the wrong card entirely."""
    fill = SanityFill()
    by_set: dict[tuple, list[dict]] = {}
    for card in crawl.cards:
        if card.get("id") in crawl.prices and card.get("name"):
            card_set = card.get("set") or {}
            by_set.setdefault(
                (card_set.get("id"), card_set.get("name")), []).append(card)

    for (set_id, set_name), cards_in_set in sorted(
            by_set.items(), key=lambda kv: kv[0][1] or ""):
        try:
            group_id = tcgcsv.group_id_for_set(set_name, set_id)
            candidates = tcgcsv.candidates_for_group(group_id) if group_id else {}
        except Exception as exc:
            log.warning("  sanity %-24s lookup error: %s", set_name, exc)
            continue
        if not candidates:
            continue
        fill.sets_checked += 1
        for card in cards_in_set:
            prices = tcgcsv.pick_product(
                candidates.get(tcgcsv.norm_number(card.get("number") or "")),
                card["name"], require_name=True)
            tcgplayer_price = (
                extract_price({"tcgplayer": {"prices": prices}}) if prices else None)
            upstream_price = crawl.prices[card["id"]]
            if not tcgplayer_price or not upstream_price:
                continue
            if (upstream_price < tcgplayer_price * _SANITY_RATIO
                    and tcgplayer_price < upstream_price * _SANITY_RATIO):
                continue
            block = card.setdefault("tcgplayer", {})
            block["prices"] = prices
            block["priceSource"] = "tcgcsv"
            crawl.prices[card["id"]] = tcgplayer_price
            fill.replaced[card["id"]] = tcgplayer_price
            log.info("  sanity %-18s upstream $%.2f vs TCGplayer $%.2f — "
                     "using TCGplayer", card["id"], upstream_price, tcgplayer_price)
    return fill


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


def recover_dropped(db, crawl: Crawl) -> DroppedFill:
    """Last-resort price source for cards on DROPPED pages — pages pokemontcg.io
    couldn't serve even after the retry pass. `_collect` never saw their cards,
    so they're absent from crawl.cards/prices/unpriced and neither tcgcsv_fill
    nor ebay_fill (both driven by crawl.unpriced) can reach them.

    The metadata those cards need is recovered from the local catalog: any card
    the catalog holds that this run did NOT crawl is — barring the rare upstream
    deletion — exactly a dropped page's card. Each is matched to the independent
    TCGCSV mirror by set + number and snapshotted, so a page pokemontcg.io
    couldn't serve still gets a same-day point instead of a hole in the series.
    The TCGCSV matching is the same code the regular fill uses: the recovered
    cards are presented as a mini-crawl whose every card is an unpriced
    candidate (we couldn't fetch their real price this run, so a fresh TCGCSV
    price is the one to record).

    The caller gates this on a synced catalog and a full (non --max-pages) run —
    without those, "not crawled this run" doesn't mean "dropped", and a brand-new
    card the catalog has never seen still has to wait for the next full crawl
    (we have no set/number to match it on until then).
    """
    fill = DroppedFill()
    crawled = {c["id"] for c in crawl.cards}
    catalog_ids = [cid for (cid,) in db.query(CatalogCard.card_id).all()]
    missing_ids = [cid for cid in catalog_ids if cid not in crawled]
    fill.candidates = len(missing_ids)
    if not missing_ids:
        return fill

    mini = Crawl()
    for i in range(0, len(missing_ids), _DEDUPE_CHUNK):
        rows = (db.query(CatalogCard)
                  .filter(CatalogCard.card_id.in_(missing_ids[i:i + _DEDUPE_CHUNK]))
                  .all())
        for row in rows:
            # deepcopy: tcgcsv_fill mutates the tcgplayer block in place, and the
            # row's JSON is still attached to the session — don't touch it
            data = copy.deepcopy(row.data) if row.data else None
            if not data or not data.get("id") or not data.get("name"):
                continue
            mini.cards.append(data)
            card_set = data.get("set") or {}
            mini.unpriced.append({
                "id": data["id"],
                "name": data["name"],
                "number": data.get("number"),
                "set_id": card_set.get("id"),
                "set_name": card_set.get("name"),
                "release": card_set.get("releaseDate") or "",
            })

    tfill = tcgcsv_fill(mini)
    fill.prices = tfill.prices
    fill.cards = mini.cards
    fill.sets_matched = tfill.sets_matched
    fill.sets_unmatched = tfill.sets_unmatched
    return fill


def _record_chunked(db, prices: dict[str, float]) -> int:
    """record_snapshots in _DEDUPE_CHUNK slices, keeping the per-day dedupe's
    IN() clause reasonable. Returns rows newly inserted."""
    recorded = 0
    items = list(prices.items())
    for i in range(0, len(items), _DEDUPE_CHUNK):
        recorded += record_snapshots(db, dict(items[i:i + _DEDUPE_CHUNK]))
    return recorded


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
    parser.add_argument("--no-tcgcsv", action="store_true",
                        help="skip the TCGCSV price fill for cards TCGPlayer "
                             "can't price (they fall through to the eBay pass)")
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
        recorded = _record_chunked(db, crawl.prices)

        # TCGCSV fill runs BEFORE the catalog upsert (so injected prices land
        # in the catalog rows) and BEFORE the eBay pass (so eBay only sees the
        # cards TCGCSV couldn't match).
        tfill = TcgcsvFill()
        fill_ran = not args.no_tcgcsv and not crawl.unpriced
        if not args.no_tcgcsv and crawl.unpriced:
            log.info("---- TCGCSV fill: %s cards have no TCGPlayer price ----",
                     f"{len(crawl.unpriced):,}")
            try:
                tfill = tcgcsv_fill(crawl)
                fill_ran = True
            except Exception as exc:  # best-effort — never costs the day's snapshots
                log.warning("tcgcsv fill failed: %s — unpriced cards fall "
                            "through to the eBay pass", exc)
            recorded += _record_chunked(db, tfill.prices)

        # Cross-check the upstream prices against TCGplayer's own mirror; a
        # wild divergence (wrong product mapped upstream, junk figure) is
        # corrected before the variant rows and catalog upsert read the dicts.
        sanity = SanityFill()
        if not args.no_tcgcsv:
            try:
                sanity = price_sanity_check(crawl)
            except Exception as exc:  # best-effort like the fill
                log.warning("price sanity check failed: %s — upstream prices "
                            "kept as-is", exc)
            # same-day re-record refreshes the corrected cards' rows in place
            recorded += _record_chunked(db, sanity.replaced)

        # Per-variant history for multi-variant cards (their headline row only
        # covers the preferred variant). After the TCGCSV fill, so injected
        # variant blocks get their series too.
        variant_rows = 0
        for i in range(0, len(crawl.cards), _DEDUPE_CHUNK):
            variant_rows += record_variant_snapshots(db, crawl.cards[i:i + _DEDUPE_CHUNK])

        # Mirror the crawled cards into the local catalog the app browses from.
        # Best-effort: a catalog failure never costs the day's snapshots. The
        # sync marker (which lets list endpoints trust the catalog) is stamped
        # only by a complete, un-truncated crawl — never a --max-pages smoke run.
        # When the TCGCSV fill ran, this upsert is authoritative
        # (keep_stored_prices=False): every card here carries fresh upstream
        # data plus the fill's arbitration, so a card that STILL has no prices
        # block has no priceable source left, and its stored block (a price no
        # source backs any more — upstream retracts bad data) must clear
        # rather than fossilize.
        upserted = 0
        try:
            for i in range(0, len(crawl.cards), _DEDUPE_CHUNK):
                upserted += card_catalog.upsert_cards(
                    db, crawl.cards[i:i + _DEDUPE_CHUNK],
                    keep_stored_prices=not fill_ran)
            if crawl.complete and not args.max_pages:
                card_catalog.mark_full_sync(db)
        except Exception as exc:
            db.rollback()
            log.warning("catalog upsert failed: %s — browsing falls back to the "
                        "upstream proxy until the next run", exc)

        remaining = [c for c in crawl.unpriced if c["id"] not in tfill.prices]
        fill = EbayFill()
        if args.max_ebay > 0 and remaining:
            log.info("---- eBay fill: %s cards still unpriced after TCGCSV ----",
                     f"{len(remaining):,}")
            fill = ebay_fill(db, remaining, args.max_ebay, args.ebay_pause)
            recorded += _record_chunked(db, fill.prices)

        # Dropped-page recovery: pages pokemontcg.io couldn't serve even after
        # the retry pass left their cards out of the crawl entirely, so nothing
        # above priced them. Pull those cards from the catalog and price them
        # from the independent TCGCSV mirror — a page upstream couldn't serve
        # still gets a same-day point instead of a gap. Only meaningful on a full
        # run against an already-synced catalog (else "uncrawled" ≠ "dropped").
        dfill = DroppedFill()
        if (crawl.dropped and not args.no_tcgcsv and not args.max_pages
                and card_catalog.is_synced(db)):
            log.info("---- dropped-page recovery: %d dropped page(s), pricing "
                     "their cards from TCGCSV via the catalog ----",
                     len(crawl.dropped))
            try:
                dfill = recover_dropped(db, crawl)
            except Exception as exc:  # best-effort — never costs the rest of the run
                log.warning("dropped-page recovery failed: %s", exc)
            recorded += _record_chunked(db, dfill.prices)
            for i in range(0, len(dfill.cards), _DEDUPE_CHUNK):
                variant_rows += record_variant_snapshots(
                    db, dfill.cards[i:i + _DEDUPE_CHUNK])
            try:  # refresh the recovered cards' catalog price too — the dicts
                #    are the stored rows themselves plus the fresh TCGCSV fill,
                #    so writing them verbatim (no keep-rule) can only refresh
                for i in range(0, len(dfill.cards), _DEDUPE_CHUNK):
                    card_catalog.upsert_cards(db, dfill.cards[i:i + _DEDUPE_CHUNK],
                                              keep_stored_prices=False)
            except Exception as exc:
                db.rollback()
                log.warning("catalog upsert (recovery) failed: %s — recovered "
                            "prices still snapshotted", exc)

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
    if not args.no_tcgcsv:
        log.info("  tcgcsv fill       %s cards priced  (%d sets matched, "
                 "%d unmatched)", f"{len(tfill.prices):,}",
                 tfill.sets_matched, len(tfill.sets_unmatched))
        log.info("  sanity check      %d upstream price(s) overridden from "
                 "TCGplayer  (%d sets compared)",
                 len(sanity.replaced), sanity.sets_checked)
    if args.max_ebay > 0:
        log.info("  ebay fill         %d priced of %d tried  (%s eligible, "
                 "%d without recent sales, %d failed fetches)%s",
                 len(fill.prices), fill.attempted, f"{fill.eligible:,}",
                 fill.no_sales, fill.failures,
                 "  — stopped early" if fill.gave_up else "")
    log.info("  snapshots today   +%s new", f"{recorded:,}")
    log.info("  variant rows      +%s new  (multi-variant cards)", f"{variant_rows:,}")
    if compacted:
        log.info("  compacted         %d month(s) to cold storage", len(compacted))
    if crawl.dropped:
        log.info("  dropped recovery  %s of %s dropped-page cards priced from TCGCSV",
                 f"{len(dfill.prices):,}", f"{dfill.candidates:,}")
        log.warning("  dropped pages     %s — the rest get caught next run",
                    ", ".join(map(str, crawl.dropped)))
    log.info(bar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
