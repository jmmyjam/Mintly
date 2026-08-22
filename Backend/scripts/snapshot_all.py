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
Card image URLs are HEAD-checked once each (`image_fill`): where upstream's
image CDN 404s (it answers with a card-back PNG browsers render as artwork),
the card is re-pointed at the TCGplayer product scan from the same mirror.
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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import certifi
import requests
from dotenv import load_dotenv

# Run as a plain script (python scripts/snapshot_all.py), so put Backend/ on the
# path to make the `app` package importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal  # noqa: E402
from app.models import CatalogCard  # noqa: E402
from app.services import (  # noqa: E402
    card_catalog, ebay_prices, history_archive, tcgcsv, watchlist_alerts,
)
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
# Page 1 carries totalCount, so the whole crawl can't start without it — a
# transient upstream 500 / DNS blip there otherwise aborts the ENTIRE day's
# snapshot (observed ~5 of 44 days). Re-try page 1 on a long, widening schedule
# (not seconds-apart like the inline backoff) so an outage has real time to
# clear before we give up: waits of 5/10/20/40 min ≈ a 75-minute recovery window.
_PAGE1_RETRY_PASSES = 4
_PAGE1_RETRY_PAUSE = 300   # cool-down before the first page-1 re-try; doubles each pass

# The full frontend field set (mirrors _CARD_FIELDS in app/routers/cards.py):
# the crawl now feeds the card_catalog table too, so browsing is served from
# the DB; set carries the name + releaseDate the eBay pass needs as well
_SELECT = "id,name,number,rarity,artist,hp,types,images,set,tcgplayer"
_EBAY_PAUSE = 3.0          # be gentle on eBay between scrapes (--ebay-pause overrides)
_EBAY_GIVEUP = 5           # consecutive FAILED fetches — blocked or offline, stop
_EBAY_MAX = 500           # default --max-ebay: caps the eBay pass per run (--max-ebay overrides)

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
class VarietyFill:
    """Stamp/mark varieties forked into their own synthetic catalog cards: a
    [Staff] stamp, error print, etc. sharing a base card's number, tracked as
    separate cards from the regular version (finishes never fork — they're
    sub-types of one product and stay on the base card)."""
    cards: list[dict] = field(default_factory=list)
    prices: dict[str, float] = field(default_factory=dict)


@dataclass
class ImageFill:
    """What the image check did: upstream image URLs verified, and cards whose
    image the upstream CDN doesn't have re-pointed at the TCGplayer scan."""
    checked: int = 0      # HEAD requests actually sent this run
    substituted: dict[str, str] = field(default_factory=dict)  # id -> new small URL
    missing: list[str] = field(default_factory=list)  # 404 and no substitute either
    errors: int = 0       # network flakes — those cards get re-checked next run


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
    failing every sweep too. Page 1 is special — it carries totalCount, so the
    crawl can't start without it — and gets its own long, widening retry schedule
    before we give up, so a blip there doesn't cost the whole day."""
    crawl = Crawl()
    first = _get_page(1)
    if first is None:
        # Page 1 failed every inline retry (seconds apart). Rather than abort the
        # entire day, re-try it on a long, widening schedule so a transient
        # upstream/network outage has real time to clear.
        cooldown = _PAGE1_RETRY_PAUSE
        for sweep in range(1, _PAGE1_RETRY_PASSES + 1):
            log.warning("page 1 failed every inline retry; sweep %d/%d — waiting "
                        "%ds for upstream to recover", sweep, _PAGE1_RETRY_PASSES,
                        cooldown)
            time.sleep(cooldown)
            cooldown *= 2
            first = _get_page(1)
            if first is not None:
                log.info("page 1 recovered on retry sweep %d", sweep)
                break
    if first is None:
        return crawl  # upstream down the whole window — genuinely nothing to record

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


def _apply_tcgcsv_block(card: dict, candidate: dict) -> None:
    """Inject a picked TCGCSV product's prices into a card dict. The
    priceSource mark keeps the request-path catalog refresh from overwriting
    the block with upstream's figure (see upsert_cards); any existing
    url/updatedAt survives alongside — a direct TCGplayer product url is added
    only when the card has none (the buy links on CardDetail read it)."""
    block = card.setdefault("tcgplayer", {})
    block["prices"] = candidate["prices"]
    block["priceSource"] = "tcgcsv"
    if not block.get("url") and candidate.get("productId"):
        block["url"] = f"https://www.tcgplayer.com/product/{candidate['productId']}"


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
            candidate = tcgcsv.pick_candidate(
                candidates.get(tcgcsv.norm_number(card.get("number") or "")),
                card.get("name"))
            full = by_id.get(card["id"])
            if candidate is None or not candidate["prices"] or full is None:
                continue
            price = extract_price({"tcgplayer": {"prices": candidate["prices"]}})
            if price is None:
                continue  # no variant the app reads — leave the card untouched
            _apply_tcgcsv_block(full, candidate)
            fill.prices[card["id"]] = price
        log.info("  tcgcsv %-24s %d/%d cards priced",
                 set_name, len(fill.prices) - before, len(cards_in_set))
    if fill.sets_unmatched:
        log.info("  tcgcsv: no match for set(s): %s — those cards fall through "
                 "to the eBay pass", ", ".join(fill.sets_unmatched))
    return fill


def _make_variety(base_card: dict, candidate: dict) -> dict | None:
    """A synthetic catalog card for one stamp/mark variety of a base card,
    priced from its own TCGplayer product. None if the product carries no price
    the app can read. Metadata pokemontcg.io owns (rarity/artist/hp/types) is
    left off — TCGCSV doesn't have it; the frontend renders those chips only
    when present."""
    pid = candidate.get("productId")
    prices = candidate.get("prices") or {}
    if pid is None or not prices:
        return None
    if extract_price({"tcgplayer": {"prices": prices}}) is None:
        return None
    variety = {
        "id": tcgcsv.variety_id(base_card["id"], pid),
        "name": tcgcsv.variety_name(candidate.get("name") or base_card.get("name") or ""),
        "number": base_card.get("number"),
        "set": base_card.get("set"),
        "tcgplayer": {
            "prices": prices,
            "priceSource": "tcgcsv",
            "url": f"https://www.tcgplayer.com/product/{pid}",
        },
        "varietyOf": base_card["id"],
    }
    # The TCGplayer product scan for the stamped card if there is one; else the
    # base card's art (a [Staff] stamp is the same illustration), so the tile is
    # never blank.
    images = tcgcsv.product_images(candidate) or base_card.get("images")
    if images:
        variety["images"] = images
    return variety


def variety_fill(crawl: Crawl) -> VarietyFill:
    """Fork every stamped/marked TCGplayer product sharing a base card's number
    into its own synthetic catalog card (a [Staff] stamp, [W Stamped], a
    (Black Dot Error), a prerelease stamp, ...), so each is searched, charted,
    and held separately. Reuses the same TCGCSV group candidates the price/image
    passes already warmed; matching is name-aware so a different card colliding
    on a number is never forked, and finishes never fork (one product = one
    candidate). Best-effort per card — a lookup failure just skips it."""
    fill = VarietyFill()
    for base in crawl.cards:
        card_set = base.get("set") or {}
        number, name = base.get("number"), base.get("name")
        if not base.get("id") or not number or not name:
            continue
        try:
            group_id = tcgcsv.group_id_for_set(card_set.get("name"), card_set.get("id"))
            if group_id is None:
                continue
            candidates = tcgcsv.candidates_for_group(group_id).get(
                tcgcsv.norm_number(number))
            varieties = tcgcsv.variety_candidates(candidates, name)
        except Exception as exc:  # the service is best-effort, but never trust that
            log.warning("  variety lookup error for %s: %s", base.get("id"), exc)
            continue
        for cand in varieties:
            card = _make_variety(base, cand)
            if card is None:
                continue
            fill.cards.append(card)
            fill.prices[card["id"]] = extract_price(card)
    if fill.cards:
        log.info("  varieties: %s stamped/marked cards forked into their own rows",
                 f"{len(fill.cards):,}")
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
            candidate = tcgcsv.pick_candidate(
                candidates.get(tcgcsv.norm_number(card.get("number") or "")),
                card["name"], require_name=True)
            tcgplayer_price = (
                extract_price({"tcgplayer": {"prices": candidate["prices"]}})
                if candidate else None)
            upstream_price = crawl.prices[card["id"]]
            if not tcgplayer_price or not upstream_price:
                continue
            if (upstream_price < tcgplayer_price * _SANITY_RATIO
                    and tcgplayer_price < upstream_price * _SANITY_RATIO):
                continue
            _apply_tcgcsv_block(card, candidate)
            crawl.prices[card["id"]] = tcgplayer_price
            fill.replaced[card["id"]] = tcgplayer_price
            log.info("  sanity %-18s upstream $%.2f vs TCGplayer $%.2f — "
                     "using TCGplayer", card["id"], upstream_price, tcgplayer_price)
    return fill


_IMAGE_TIMEOUT = (5, 15)
_IMAGE_WORKERS = 8   # concurrent HEADs; the image CDN is Cloudflare-cached

# Plain session for the image CDN — no API key, no upstream headers
_image_session = requests.Session()
_image_session.verify = certifi.where()


def _head_image(url: str) -> int | None:
    """The image URL's HTTP status, or None when the check itself failed."""
    try:
        return _image_session.head(url, timeout=_IMAGE_TIMEOUT).status_code
    except requests.RequestException:
        return None


def image_fill(db, crawl: Crawl) -> ImageFill:
    """Swap dead card-image URLs for the TCGplayer product scan.

    The upstream image CDN answers a MISSING card image with HTTP 404 whose
    body is a generic card-back PNG — a browser <img> renders that back as if
    it were the artwork (every card of the 2014/15/17/18 McDonald's sets, for
    example). Each crawled card's small-image URL is HEAD-checked: on 200 the
    images block is stamped `verified` (the stamp rides the catalog row, and
    upsert_cards carries it through request-path refreshes, so every URL is
    checked once ever, not once per run); on 404 the whole block is replaced
    with the TCGplayer scan of the same product match the price fills trust,
    marked `source: tcgplayer`. Substituted cards fail the verified test on
    the next crawl and get re-checked, so a card whose scan upstream later
    adds heals back to upstream's (better) images automatically."""
    fill = ImageFill()
    # {card_id: the upstream small URL a previous run verified}
    verified: dict[str, str] = {}
    ids = [c["id"] for c in crawl.cards if c.get("id")]
    for i in range(0, len(ids), _DEDUPE_CHUNK):
        rows = (db.query(CatalogCard.card_id, CatalogCard.data)
                  .filter(CatalogCard.card_id.in_(ids[i:i + _DEDUPE_CHUNK])))
        for card_id, data in rows:
            images = (data or {}).get("images") or {}
            if images.get("verified") and images.get("small"):
                verified[card_id] = images["small"]

    to_check: list[dict] = []
    for card in crawl.cards:
        images = card.get("images") or {}
        if not images.get("small"):
            continue
        if verified.get(card.get("id")) == images["small"]:
            images["verified"] = True  # carry the stamp through this upsert
        else:
            to_check.append(card)
    if not to_check:
        return fill

    log.info("---- image check: %s new/changed image URL(s) to verify ----",
             f"{len(to_check):,}")
    with ThreadPoolExecutor(max_workers=_IMAGE_WORKERS) as pool:
        statuses = list(pool.map(
            lambda c: _head_image(c["images"]["small"]), to_check))

    for card, status in zip(to_check, statuses):
        fill.checked += 1
        if status == 200:
            card["images"]["verified"] = True
            continue
        if status != 404:
            fill.errors += 1  # flake or odd status — try again next run
            continue
        card_set = card.get("set") or {}
        try:
            group_id = tcgcsv.group_id_for_set(card_set.get("name"),
                                               card_set.get("id"))
            candidates = tcgcsv.candidates_for_group(group_id) if group_id else {}
            images = tcgcsv.product_images(tcgcsv.pick_candidate(
                candidates.get(tcgcsv.norm_number(card.get("number") or "")),
                card.get("name")))
        except Exception as exc:  # best-effort service, but never trust that
            log.warning("  images %-18s lookup error: %s", card.get("id"), exc)
            images = None
        if images:
            card["images"] = images
            fill.substituted[card["id"]] = images["small"]
            log.info("  images %-18s upstream 404 — using the TCGplayer scan",
                     card["id"])
        else:
            # leave upstream's URLs in place: the frontend detects the 404
            # card-back and shows its placeholder, and a later run re-checks
            fill.missing.append(card["id"])
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
    parser.add_argument("--no-archive", action="store_true",
                        help="skip backing up complete old months to cold-storage "
                             "CSVs (DB rows are kept either way)")
    parser.add_argument("--no-alerts", action="store_true",
                        help="skip evaluating watchlist price alerts / sending "
                             "their emails (for smoke tests)")
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

        # Swap dead image URLs for TCGplayer scans BEFORE the catalog upsert,
        # so the fixed blocks land in the rows the app serves. Gated with the
        # other TCGCSV passes: substitutes come from the same mirror.
        ifill = ImageFill()
        if not args.no_tcgcsv:
            try:
                ifill = image_fill(db, crawl)
            except Exception as exc:  # best-effort like the fills
                log.warning("image check failed: %s — image URLs kept as-is", exc)

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

        # Fork stamped/marked TCGplayer products (a [Staff] stamp, error print,
        # etc. sharing a base card's number) into their own synthetic catalog
        # cards, snapshotted + upserted like any card. Runs after the base
        # upsert and reuses the group candidates the passes above warmed; gated
        # with the other TCGCSV work and best-effort (a failure never costs the
        # base-card snapshots).
        vfill = VarietyFill()
        if not args.no_tcgcsv:
            try:
                vfill = variety_fill(crawl)
            except Exception as exc:
                log.warning("variety fill failed: %s — no varieties this run", exc)
            recorded += _record_chunked(db, vfill.prices)
            for i in range(0, len(vfill.cards), _DEDUPE_CHUNK):
                variant_rows += record_variant_snapshots(
                    db, vfill.cards[i:i + _DEDUPE_CHUNK])
            try:  # authoritative like the base upsert — variety dicts are freshly
                #    built from the mirror, so keep-rules would only get in the way
                for i in range(0, len(vfill.cards), _DEDUPE_CHUNK):
                    card_catalog.upsert_cards(db, vfill.cards[i:i + _DEDUPE_CHUNK],
                                              keep_stored_prices=False)
            except Exception as exc:
                db.rollback()
                log.warning("catalog upsert (varieties) failed: %s — variety "
                            "prices still snapshotted", exc)

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

        # Watchlist price alerts: every card's price for today is now recorded,
        # so evaluate each user's alert thresholds against the fresh snapshots and
        # email whoever's card crossed. Best-effort and edge-triggered (a re-arm
        # latch stops a card past its target from re-alerting daily) — see
        # app/services/watchlist_alerts.py. Never costs the day's snapshots.
        alerts = watchlist_alerts.AlertRun()
        if not args.no_alerts:
            try:
                alerts = watchlist_alerts.evaluate(db)
            except Exception as exc:  # best-effort like the fills
                db.rollback()
                log.warning("watchlist alert evaluation failed: %s", exc)

        archived_months: list[dict] = []
        if not args.no_archive:
            try:
                archived_months = history_archive.archive(db)
            except Exception as exc:  # the backup must never cost us the day's snapshots
                log.warning("history archive failed: %s — the DB still holds "
                            "every row; retries next run", exc)
            for c in archived_months:
                log.info("  backed up %s: %s rows -> %s",
                         c["month"], f"{c['rows_archived']:,}", c["path"])
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
        log.info("  image check       %s URL(s) checked, %d swapped to the "
                 "TCGplayer scan, %d without an image anywhere, %d check "
                 "errors", f"{ifill.checked:,}", len(ifill.substituted),
                 len(ifill.missing), ifill.errors)
        log.info("  varieties         %s stamped/marked cards forked into own rows",
                 f"{len(vfill.cards):,}")
    if args.max_ebay > 0:
        log.info("  ebay fill         %d priced of %d tried  (%s eligible, "
                 "%d without recent sales, %d failed fetches)%s",
                 len(fill.prices), fill.attempted, f"{fill.eligible:,}",
                 fill.no_sales, fill.failures,
                 "  — stopped early" if fill.gave_up else "")
    log.info("  snapshots today   +%s new", f"{recorded:,}")
    log.info("  variant rows      +%s new  (multi-variant cards)", f"{variant_rows:,}")
    if not args.no_alerts:
        log.info("  watchlist alerts  %d sent to %d user(s)  (%d re-armed, "
                 "%d send failures)", alerts.alerts_sent, alerts.users_notified,
                 alerts.rearmed, alerts.failures)
    if archived_months:
        log.info("  archived          %d month(s) backed up to cold storage",
                 len(archived_months))
    if crawl.dropped:
        log.info("  dropped recovery  %s of %s dropped-page cards priced from TCGCSV",
                 f"{len(dfill.prices):,}", f"{dfill.candidates:,}")
        log.warning("  dropped pages     %s — the rest get caught next run",
                    ", ".join(map(str, crawl.dropped)))
    log.info(bar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
