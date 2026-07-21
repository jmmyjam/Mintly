"""TCGplayer prices via TCGCSV (tcgcsv.com) for cards pokemontcg.io can't price.

pokemontcg.io lags on brand-new sets — their cards arrive with an empty
`tcgplayer.prices` block. TCGCSV is a free nightly mirror of TCGplayer's own
catalog + price files (refreshed daily at 20:00 UTC) that already carries real,
variant-separated prices for those sets. The daily snapshot job uses it to fill
exactly that gap; eBay sold listings stay as the last resort for whatever this
can't match.

Joining is by set + card number: a pokemontcg.io set name is matched to a
TCGplayer "group" (their names carry a `"ME05: "`-style code prefix ours don't),
and card numbers are normalized on both sides (`"001/084"` → `"1"`). Returned
price dicts are shaped exactly like pokemontcg.io's `tcgplayer.prices`
(`{variant: {low, mid, high, market}}`), so `extract_price` and the frontend
read them unchanged.

Best-effort like the eBay estimator: any fetch/parse failure returns empty /
`None`, never raises — an unmatched set just falls through to the eBay pass.
"""
import logging
import re

import certifi
import requests

log = logging.getLogger(__name__)

# ----- Configuration ---------------------------------------------------------

_BASE_URL = "https://tcgcsv.com/tcgplayer"
_CATEGORY = 3  # TCGplayer's category id for Pokemon
_TIMEOUT = (5, 30)

# TCGplayer subTypeName -> the variant keys pokemontcg.io uses (extract_price
# and the frontend's getCardPrice read these). Vintage WOTC groups say
# "Unlimited"/"1st Edition" where pokemontcg.io says normal/holofoil etc. —
# same mapping pokemontcg.io itself applies. Unknown names are camelCased.
_VARIANT_KEYS = {
    "Normal": "normal",
    "Holofoil": "holofoil",
    "Reverse Holofoil": "reverseHolofoil",
    "1st Edition Holofoil": "1stEditionHolofoil",
    "1st Edition Normal": "1stEditionNormal",
    "1st Edition": "1stEditionNormal",
    "Unlimited": "normal",
    "Unlimited Holofoil": "holofoil",
}

# Stubborn set-name mismatches: pokemontcg.io set id -> TCGplayer groupId.
# Checked before name matching; add entries as unmatched sets show up in the
# snapshot job's log (verify the group's card-number format joins first —
# e.g. the Trainer Kits are deliberately absent: TCGplayer merges both
# half-decks into one group, and their card numbers collide).
_GROUP_OVERRIDES: dict[str, int] = {
    "base1": 604,    # "Base" -> "Base Set"
    "sm1": 1863,     # "Sun & Moon" -> "SM Base Set"
    "swshp": 2545,   # "SWSH Black Star Promos" -> "SWSH: Sword & Shield Promo Cards"
    "svp": 22872,    # "Scarlet & Violet Black Star Promos" -> "SV: ... Promo Cards"
    "smp": 1861,     # "SM Black Star Promos" -> "SM Promos"
    "xyp": 1451,     # "XY Black Star Promos" -> "XY Promos"
    "mcd17": 2148,   # "McDonald's Collection 2017" -> "McDonald's Promos 2017"
    "mcd18": 2364,   # "McDonald's Collection 2018" -> "McDonald's Promos 2018"
}

# TCGplayer group names carry a leading set code ("ME05: Pitch Black") or era
# tag ("XY - Ancient Origins", "SM - Burning Shadows")
_CODE_PREFIX_RE = re.compile(r"^[A-Za-z0-9]{1,10}(:\s*|\s+[-–—]\s+)")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_AND_RE = re.compile(r"\band\b")  # "Diamond and Pearl" ↔ "Diamond & Pearl"


# ----- Global state ----------------------------------------------------------

# The job runs as one process per day, so plain memos are enough: the groups
# list and each group's joined prices are fetched at most once per run.
_groups_cache: dict[str, int] | None = None
_prices_cache: dict[int, dict[str, dict]] = {}

_session = requests.Session()
_session.verify = certifi.where()
# tcgcsv.com 401s the default python-requests user agent; an honest
# identifying UA is accepted (verified July 21, 2026)
_session.headers.update(
    {"User-Agent": "Mintly/1.0 (Pokemon TCG portfolio tracker; daily price sync)"})


# ----- Fetch (monkeypatched in tests) ----------------------------------------

def _fetch_results(path: str) -> list | None:
    """One TCGCSV JSON file's `results` list, or None on any failure."""
    try:
        resp = _session.get(f"{_BASE_URL}/{path}", timeout=_TIMEOUT)
        if resp.status_code != 200:
            log.warning("tcgcsv %s: HTTP %d", path, resp.status_code)
            return None
        results = resp.json().get("results")
        return results if isinstance(results, list) else None
    except (requests.RequestException, ValueError) as exc:
        log.warning("tcgcsv %s: %s", path, exc)
        return None


def _fetch_groups() -> list | None:
    return _fetch_results(f"{_CATEGORY}/groups")


def _fetch_products(group_id: int) -> list | None:
    return _fetch_results(f"{_CATEGORY}/{group_id}/products")


def _fetch_prices(group_id: int) -> list | None:
    return _fetch_results(f"{_CATEGORY}/{group_id}/prices")


# ----- Normalization ---------------------------------------------------------

def _norm_set(name: str) -> str:
    """Comparable form of a set/group name: code/era prefix off, lowercased,
    punctuation and "and" collapsed — "ME05: Pitch Black"/"Pitch Black",
    "XY - Ancient Origins"/"Ancient Origins", and "Diamond and Pearl"/
    "Diamond & Pearl" each normalize to the same string."""
    name = _CODE_PREFIX_RE.sub("", name.strip())
    name = _NON_ALNUM_RE.sub(" ", name.lower())
    return " ".join(_AND_RE.sub(" ", name).split())


def norm_number(value: str) -> str:
    """Comparable form of a card number: the part before any "/", leading
    zeros stripped, lowercased — TCGCSV's "001/084" matches pokemontcg.io's
    "1"; alphanumeric numbers ("TG12", "SWSH039") pass through intact."""
    part = value.split("/")[0].strip().lower()
    return part.lstrip("0") or "0"


def _variant_key(sub_type: str) -> str:
    known = _VARIANT_KEYS.get(sub_type)
    if known:
        return known
    words = sub_type.split()
    return words[0].lower() + "".join(w.capitalize() for w in words[1:])


# ----- Public API ------------------------------------------------------------

def group_id_for_set(set_name: str | None, set_id: str | None = None) -> int | None:
    """The TCGplayer groupId for a pokemontcg.io set, or None if unmatched.
    The override map (keyed by set id) wins; otherwise normalized name match."""
    if set_id and set_id in _GROUP_OVERRIDES:
        return _GROUP_OVERRIDES[set_id]
    if not set_name:
        return None

    global _groups_cache
    if _groups_cache is None:
        groups = _fetch_groups()
        if groups is None:
            return None  # leave the cache unset so a later call can retry
        _groups_cache = {
            _norm_set(g["name"]): g["groupId"]
            for g in groups
            if g.get("name") and g.get("groupId") is not None
        }
    return _groups_cache.get(_norm_set(set_name))


def prices_for_group(group_id: int) -> dict[str, dict]:
    """One group's card prices joined product×price, keyed by normalized card
    number: {number: {variant: {low, mid, high, market}}}. Empty on any
    failure. Fetched once per group per run."""
    cached = _prices_cache.get(group_id)
    if cached is not None:
        return cached

    products = _fetch_products(group_id)
    price_rows = _fetch_prices(group_id)
    if products is None or price_rows is None:
        return {}

    # productId -> normalized number; products without a Number extendedData
    # entry are sealed/non-card items and get skipped
    numbers: dict[int, str] = {}
    for product in products:
        for entry in product.get("extendedData") or []:
            if entry.get("name") == "Number" and entry.get("value"):
                numbers[product.get("productId")] = norm_number(entry["value"])
                break

    joined: dict[str, dict] = {}
    for row in price_rows:
        number = numbers.get(row.get("productId"))
        if number is None:
            continue
        market, mid = row.get("marketPrice"), row.get("midPrice")
        if market is None and mid is None:
            continue  # nothing extract_price could use
        variant = {
            key: value
            for key, value in (("low", row.get("lowPrice")), ("mid", mid),
                               ("high", row.get("highPrice")), ("market", market))
            if value is not None
        }
        # Two products can share a number (e.g. pattern variants sold as
        # separate products); the first listed keeps each variant slot
        joined.setdefault(number, {}).setdefault(
            _variant_key(row.get("subTypeName") or "Normal"), variant)

    _prices_cache[group_id] = joined
    return joined


def card_prices(set_id: str | None, set_name: str | None,
                number: str | None) -> dict | None:
    """A `tcgplayer.prices`-shaped dict for one card, or None if TCGCSV can't
    match its set or number."""
    if not number:
        return None
    group_id = group_id_for_set(set_name, set_id)
    if group_id is None:
        return None
    return prices_for_group(group_id).get(norm_number(number)) or None
