import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path

import requests
import certifi
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from app.database import SessionLocal, get_db
from app.services import card_catalog, ebay_prices
from app.services.price_history import annotate_price_changes, attach_estimates, card_history
from app.services.rate_limit import rate_limit

logger = logging.getLogger(__name__)

load_dotenv()


# ----- Configuration ---------------------------------------------------------

BASE_URL = "https://api.pokemontcg.io/v2"
API_KEY = os.getenv("POKEMON_TCG_API_KEY")

_CACHE_TTL = 21600  # fresh for 6 hours...
_STALE_TTL = 86400  # ...then served stale (with a background refresh) up to 24h

# Cache entries are mirrored to disk and reloaded at startup, so the many
# --reload restarts of a dev session don't each start cold; the default dir
# sits at the Backend root (two levels up from app/routers/)
_CACHE_DIR = Path(os.getenv(
    "CARD_CACHE_DIR", Path(__file__).resolve().parents[2] / ".cache" / "cards"
))

# Upstream latency scales with the *requested* page size, not the payload:
# pageSize=250 (the upstream max) benchmarks at 20-60s and drops connections,
# pageSize=50 at 2-5s — don't raise this without re-measuring
_PAGE_SIZE = 50

# Upstream is legitimately slow on cold queries (tens of seconds) but must never
# hang a worker forever: 5s to connect, 60s per read.
_TIMEOUT = (5, 60)

# Only the fields the frontend uses — full card objects (attacks, legalities, etc.)
# are several times larger and slower for the upstream API to serve
_CARD_FIELDS = "id,name,number,rarity,artist,hp,types,images,set,tcgplayer"


# ----- Global state ----------------------------------------------------------

_cache: dict[str, tuple[float, list | dict]] = {}

# Keys with a background refresh in flight, so a popular stale entry doesn't
# spawn one upstream call per request
_refreshing: set[str] = set()
_refreshing_lock = threading.Lock()

session = requests.Session()
session.verify = certifi.where()
session.headers.update({"X-Api-Key": API_KEY})

# One general per-IP budget across all card AND portfolio endpoints (the
# portfolio router registers the same "api" scope) — generous for a browsing
# human, a wall for a scraper burning the upstream API quota
router = APIRouter(dependencies=[Depends(rate_limit("api", times=120, seconds=60))])


# ----- Upstream fetch helpers (cached) ----------------------------------------
# Entries are fresh for _CACHE_TTL; after that they're served stale immediately
# while one background thread re-fetches (a user should never wait out a slow
# upstream call for data we already have). Past _STALE_TTL the entry is dead
# and the fetch happens synchronously again.

def _cache_get(key: str) -> tuple[list | dict, bool] | None:
    """Return (data, is_fresh), or None if absent or too stale to serve."""
    entry = _cache.get(key)
    if not entry:
        return None
    age = time.time() - entry[0]
    if age >= _STALE_TTL:
        return None
    return entry[1], age < _CACHE_TTL


def _cache_path(key: str) -> Path:
    # keys hold query syntax (quotes, |, :) — hash them into safe filenames
    return _CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".json")


def _cache_put(key: str, data: list | dict) -> None:
    ts = time.time()
    _cache[key] = (ts, data)
    # Mirror to disk best-effort: a failed write only costs persistence.
    # Written before annotate_price_changes runs, so files never carry
    # priceChange — it's recomputed per request.
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        blob = json.dumps({"key": key, "ts": ts, "data": data})
        with tempfile.NamedTemporaryFile("w", dir=_CACHE_DIR, suffix=".tmp",
                                         delete=False) as tmp:
            tmp.write(blob)
        os.replace(tmp.name, _cache_path(key))  # atomic — no partial reads
    except OSError:
        logger.warning("could not persist cache entry %r", key)


def _load_persisted_cache() -> int:
    """Restore disk-mirrored entries younger than _STALE_TTL; prune the rest."""
    loaded = 0
    try:
        files = list(_CACHE_DIR.glob("*.json"))
        for leftover in _CACHE_DIR.glob("*.tmp"):  # interrupted writes
            leftover.unlink(missing_ok=True)
    except OSError:
        return 0
    for f in files:
        try:
            entry = json.loads(f.read_text())
            if time.time() - entry["ts"] < _STALE_TTL:
                _cache[entry["key"]] = (entry["ts"], entry["data"])
                loaded += 1
            else:
                f.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError):
            try:
                f.unlink(missing_ok=True)  # corrupt file — drop it
            except OSError:
                pass
    return loaded


def _refresh_in_background(key: str, fetch) -> None:
    # fetch() re-fetches upstream and overwrites _cache[key]; on failure the
    # stale entry stays and the next request triggers another attempt
    with _refreshing_lock:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def run():
        try:
            fetch()
        except Exception:
            pass
        finally:
            with _refreshing_lock:
                _refreshing.discard(key)

    threading.Thread(target=run, daemon=True).start()


_restored = _load_persisted_cache()
if _restored:
    logger.info("restored %d cached upstream responses from disk", _restored)


def _fetch_cards(q: str, page: int = 1) -> dict:
    key = f"{q}|page:{page}"
    cached = _cache_get(key)
    if cached is not None:
        data, fresh = cached
        if not fresh:
            _refresh_in_background(key, lambda: _fetch_cards_upstream(key, q, page))
        return data
    return _fetch_cards_upstream(key, q, page)


def _fetch_cards_upstream(key: str, q: str, page: int) -> dict:
    try:
        response = session.get(
            f"{BASE_URL}/cards",
            params={"q": q, "select": _CARD_FIELDS, "page": page, "pageSize": _PAGE_SIZE},
            timeout=_TIMEOUT,
        )
    except requests.RequestException:
        raise HTTPException(status_code=504, detail="Failed to fetch cards")
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch cards")
    payload = response.json()
    cards = payload.get("data", [])
    data = {
        "data": cards,
        "page": page,
        "pageSize": payload.get("pageSize", _PAGE_SIZE),
        "totalCount": payload.get("totalCount", len(cards)),
    }
    _cache_put(key, data)
    return data


def _fetch_card(card_id: str) -> dict:
    key = f"__card__{card_id}"
    cached = _cache_get(key)
    if cached is not None:
        data, fresh = cached
        if not fresh:
            _refresh_in_background(key, lambda: _fetch_card_upstream(key, card_id))
        return data
    return _fetch_card_upstream(key, card_id)


def _fetch_card_upstream(key: str, card_id: str) -> dict:
    try:
        response = session.get(f"{BASE_URL}/cards/{card_id}", timeout=_TIMEOUT)
    except requests.RequestException:
        raise HTTPException(status_code=504, detail="Failed to fetch card")
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Card not found")
    data = response.json().get("data", {})
    _cache_put(key, data)
    return data


def _fetch_sets() -> list:
    cached = _cache.get("__sets__")
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]
    if cached:
        # The sets list barely changes, but sits on hot paths (smart search's
        # set-name matching, the set-page completeness check) — never block a
        # request on the upstream refresh (observed 404s / 50s hangs): serve
        # stale at any age while one background thread re-fetches
        _refresh_in_background("__sets__", _fetch_sets_upstream)
        return cached[1]
    return _fetch_sets_upstream()


def _fetch_sets_upstream() -> list:
    try:
        response = session.get(f"{BASE_URL}/sets", timeout=_TIMEOUT)
    except requests.RequestException:
        response = None
    if response is None or response.status_code != 200:
        cached = _cache.get("__sets__")
        if cached:
            return cached[1]  # flake with a cached copy — keep serving it
        raise HTTPException(
            status_code=response.status_code if response is not None else 504,
            detail="Failed to fetch sets",
        )
    data = response.json().get("data", [])
    _cache_put("__sets__", data)
    return data


# ----- Local catalog ---------------------------------------------------------
# The card_catalog table (filled by the daily crawl) answers browsing straight
# from the DB. All catalog access here is best-effort: a DB hiccup drops us
# back to the upstream proxy, never to a 500.

def _catalog_ready(db: Session) -> bool:
    # List endpoints only trust the catalog after a complete crawl has stamped
    # the sync marker — a partial catalog would serve confidently-short pages
    try:
        return card_catalog.is_synced(db)
    except Exception:
        db.rollback()
        logger.warning("catalog sync check failed", exc_info=True)
        return False


def _catalog_row(db: Session, card_id: str):
    try:
        return card_catalog.get_card(db, card_id)
    except Exception:
        db.rollback()
        logger.warning("catalog lookup failed", exc_info=True)
        return None


def _upsert_results(db: Session, results: dict) -> None:
    # Proxied responses top up the catalog (so new sets appear before the next
    # crawl); called before annotation so priceChange never persists
    try:
        card_catalog.upsert_cards(db, results.get("data", []))
    except Exception:
        db.rollback()
        logger.warning("catalog upsert failed", exc_info=True)


def refresh_card_prices(db: Session, card_ids: list[str]) -> int:
    """Synchronous core of the background price refresh: one batched upstream
    fetch for up to a page of ids, upserted into the catalog. Returns how many
    cards were refreshed (0 on any upstream failure — the stale rows just get
    another chance on the next view)."""
    if not card_ids:
        return 0
    q = " OR ".join(f'id:"{cid}"' for cid in card_ids)
    try:
        response = session.get(
            f"{BASE_URL}/cards",
            params={"q": q, "select": _CARD_FIELDS, "pageSize": len(card_ids)},
            timeout=_TIMEOUT,
        )
    except requests.RequestException:
        return 0
    if response.status_code != 200:
        return 0
    return card_catalog.upsert_cards(db, response.json().get("data", []))


def _refresh_prices_in_background(card_ids: list[str]) -> None:
    # Stale prices never block a response: serve what the catalog has and let a
    # daemon thread re-fetch (deduped per id set); the next request — or
    # CardDetail's `refreshing` poll — picks up the fresh numbers
    ids = sorted(set(card_ids))
    key = "__prices__" + hashlib.sha1("|".join(ids).encode()).hexdigest()

    def fetch():
        db = SessionLocal()
        try:
            refresh_card_prices(db, ids)
        finally:
            db.close()

    _refresh_in_background(key, fetch)


def _expected_set_total(set_id: str) -> int:
    """The set's card count per the sets list — a catalog holding fewer must
    proxy (a half-crawled new set serving short pages is worse than slow).
    Unknown set or a flaky sets fetch → 0, i.e. trust the catalog."""
    try:
        for s in _fetch_sets():
            if s.get("id") == set_id:
                return s.get("total") or 0
    except HTTPException:
        pass
    return 0


def _with_price_changes(db: Session, results: dict) -> dict:
    # Snapshot recording + daily-change annotation are best-effort: the card
    # proxy must keep answering even if the database is down
    try:
        annotate_price_changes(db, results.get("data", []))
        attach_estimates(db, results.get("data", []))
    except Exception:
        db.rollback()
        logger.warning("price-change annotation failed", exc_info=True)
    return results


# ----- Routes ----------------------------------------------------------------

# Natural language search
@router.get("/search")
def smart_search(q: str, page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    # Lowercase up front: upstream matching is case-insensitive, so "Charizard"
    # and "charizard" must build the same query and share one cache entry
    parts = q.strip().lower().replace('"', "").split()
    number = None
    set_id = None
    name_parts = []

    for part in parts:
        if re.fullmatch(r'\d+', part):
            number = part
        elif re.fullmatch(r'[a-zA-Z]+\d+', part):
            set_id = part
        else:
            name_parts.append(part)

    # Recognize set names in the query, e.g. "pikachu lost origin" (longest match wins)
    if set_id is None and name_parts:
        set_names = {s["name"].lower(): s["id"] for s in _fetch_sets()}
        n = len(name_parts)
        for size in range(n, 0, -1):
            match = None
            for start in range(n - size + 1):
                candidate = " ".join(name_parts[start:start + size]).lower()
                if candidate in set_names:
                    match = (start, size, set_names[candidate])
                    break
            if match:
                start, size, set_id = match
                name_parts = name_parts[:start] + name_parts[start + size:]
                break

    def build_query(name_words: list[str]) -> str:
        filters = []
        if name_words:
            filters.append(f'name:"{" ".join(name_words)}"')
        if number:
            filters.append(f"number:{number}")
        if set_id:
            filters.append(f"set.id:{set_id}")
        return " ".join(filters)

    if not name_parts and not number and not set_id:
        raise HTTPException(status_code=400, detail="Invalid search query")

    def catalog_query(name_words: list[str]) -> dict:
        results, stale = card_catalog.search(
            db, name=" ".join(name_words) or None, number=number,
            set_id=set_id, page=page,
        )
        if stale:
            _refresh_prices_in_background(stale)
        return results

    def upstream_query(name_words: list[str]) -> dict:
        return _fetch_cards(build_query(name_words), page)

    # Fallback for loose names like "sleepy pikachu": drop words until something
    # matches. Keyed on totalCount, not the page's data — an empty page 2 of a
    # real query must not trigger the fallback.
    def first_match(run) -> dict:
        results = run(name_parts)
        if results["totalCount"] == 0 and len(name_parts) > 1:
            for i in range(1, len(name_parts)):
                for candidate in (name_parts[i:], name_parts[:-i]):
                    results = run(candidate)
                    if results["totalCount"] > 0:
                        return results
        return results

    if _catalog_ready(db):
        results = first_match(catalog_query)
        if results["totalCount"] == 0:
            # Nothing local — a typo, or a set newer than the last crawl. One
            # cached upstream try before answering empty.
            results = first_match(upstream_query)
            _upsert_results(db, results)
    else:
        results = first_match(upstream_query)
        _upsert_results(db, results)
    return _with_price_changes(db, results)


# Search cards — supports name, set code, card number, rarity, and type
@router.get("/cards")
def search_cards(
    name: str | None = None,
    set_id: str | None = None,
    number: str | None = None,
    rarity: str | None = None,
    type: str | None = None,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    filters = []
    # name/set_id are lowercased so case variants share one cache entry (set ids
    # are lowercase upstream); rarity/type stay exact — they're era-specific
    # strings picked from dropdowns, not free text
    if name:
        filters.append(f'name:"{name.replace(chr(34), "").lower()}"')
    if set_id:
        filters.append(f"set.id:{set_id.lower()}")
    if number:
        filters.append(f"number:{number}")
    if rarity:
        filters.append(f'rarity:"{rarity}"')
    if type:
        filters.append(f"types:{type}")

    if not filters:
        raise HTTPException(status_code=400, detail="Provide at least one search parameter")

    if _catalog_ready(db):
        results, stale = card_catalog.search(
            db,
            name=name.replace(chr(34), "").lower() if name else None,
            number=number,
            set_id=set_id.lower() if set_id else None,
            rarity=rarity,
            type_=type,
            page=page,
        )
        if results["totalCount"]:
            if stale:
                _refresh_prices_in_background(stale)
            return _with_price_changes(db, results)

    results = _fetch_cards(" ".join(filters), page)
    _upsert_results(db, results)
    return _with_price_changes(db, results)


# Daily price points for one card (built from Mintly's own snapshots — the
# upstream API has no history endpoint). Default window: ~5 years.
@router.get("/cards/{card_id}/history")
def get_card_history(card_id: str, days: int = Query(1825, ge=1, le=3650), db: Session = Depends(get_db)):
    return card_history(db, card_id, days)


# Recent-sold-listings price estimate from eBay, for cards the TCGPlayer feed
# can't price (newest sets). Best-effort — returns count:0 when nothing usable.
# Extra rate limit on top of the router's: each uncached estimate is a live
# eBay scrape, and hammering those gets the server's IP bot-blocked
@router.get("/cards/{card_id}/ebay-price",
            dependencies=[Depends(rate_limit("ebay", times=60, seconds=3600,
                                             what="price-estimate requests"))])
def get_ebay_price(card_id: str, db: Session = Depends(get_db)):
    row = _catalog_row(db, card_id)
    card = card_catalog.card_payload(row) if row is not None else _fetch_card(card_id)
    return ebay_prices.estimate(
        card.get("name", ""),
        card.get("number"),
        card.get("set", {}).get("name"),
    )


# Get a single card by its API ID (e.g. base1-4)
@router.get("/cards/{card_id}")
def get_card(card_id: str, db: Session = Depends(get_db)):
    row = _catalog_row(db, card_id)
    if row is not None:
        card = card_catalog.card_payload(row)
        if card_catalog.price_is_stale(row):
            # Serve instantly anyway; a daemon thread re-fetches the price and
            # the frontend re-polls while `refreshing` is set
            card["refreshing"] = True
            _refresh_prices_in_background([card_id])
        _with_price_changes(db, {"data": [card]})
        return card
    card = _fetch_card(card_id)
    _upsert_results(db, {"data": [card]})
    _with_price_changes(db, {"data": [card]})
    return card


# List all sets
@router.get("/sets")
def get_sets():
    return _fetch_sets()


# Get a single set by its ID (e.g. base1, swsh1)
@router.get("/sets/{set_id}")
def get_set(set_id: str):
    # The cached sets list already has every set — no upstream call needed
    for s in _fetch_sets():
        if s.get("id") == set_id:
            return s
    raise HTTPException(status_code=404, detail="Set not found")


# Get all cards in a set
@router.get("/sets/{set_id}/cards")
def get_set_cards(set_id: str, page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    sid = set_id.lower()
    if _catalog_ready(db):
        have = card_catalog.set_count(db, sid)
        if have and have >= _expected_set_total(sid):
            results, stale = card_catalog.search(db, set_id=sid, page=page)
            if stale:
                _refresh_prices_in_background(stale)
            return _with_price_changes(db, results)
    results = _fetch_cards(f"set.id:{sid}", page)
    _upsert_results(db, results)
    return _with_price_changes(db, results)
