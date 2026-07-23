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
import unicodedata

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
# snapshot job's log (verify the group's card-number format joins first).
# Groups whose numbers collide across products ("1/12" is Arcanine AND Beldum
# in the merged EX Trainer Kit group; "WoTC Promo" reuses numbers across
# series) are safe to map since pick_product disambiguates by card name.
_GROUP_OVERRIDES: dict[str, int] = {
    "base1": 604,    # "Base" -> "Base Set"
    "sm1": 1863,     # "Sun & Moon" -> "SM Base Set"
    "swshp": 2545,   # "SWSH Black Star Promos" -> "SWSH: Sword & Shield Promo Cards"
    "svp": 22872,    # "Scarlet & Violet Black Star Promos" -> "SV: ... Promo Cards"
    "smp": 1861,     # "SM Black Star Promos" -> "SM Promos"
    "xyp": 1451,     # "XY Black Star Promos" -> "XY Promos"
    "dpp": 1421,     # "DP Black Star Promos" -> "Diamond and Pearl Promos"
    "hsp": 1453,     # "HGSS Black Star Promos" -> "HGSS Promos"
    "bwp": 1407,     # "BW Black Star Promos" -> "Black and White Promos"
    "np": 1423,      # "Nintendo Black Star Promos" -> "Nintendo Promos"
    "basep": 1418,   # "Wizards Black Star Promos" -> "WoTC Promo"
    "hgss2": 1399,   # "HS—Unleashed" -> "Unleashed" (no-space em dash survives
    "hgss3": 1403,   # "HS—Undaunted" -> "Undaunted"    the code-prefix strip)
    "hgss4": 1381,   # "HS—Triumphant" -> "Triumphant"
    "ecard1": 1375,  # "Expedition Base Set" -> "Expedition"
    "bp": 1455,      # "Best of Game" -> "Best of Promos"
    "ru1": 1433,     # "Pokémon Rumble" -> "Rumble"
    "xy1": 1387,     # "XY" -> "XY Base Set"
    "swsh1": 2585,   # "Sword & Shield" -> "SWSH01: Sword & Shield Base Set"
    "sv1": 22873,    # "Scarlet & Violet" -> "SV01: Scarlet & Violet Base Set"
    "sv3pt5": 23237,  # "151" -> "SV: Scarlet & Violet 151"
    "mcd11": 1401,   # "McDonald's Collection 2011" -> "McDonald's Promos 2011"
    "mcd12": 1427,   # "McDonald's Collection 2012" -> "McDonald's Promos 2012"
    "mcd14": 1692,   # "McDonald's Collection 2014" -> "McDonald's Promos 2014"
    "mcd15": 1694,   # "McDonald's Collection 2015" -> "McDonald's Promos 2015"
    "mcd16": 3087,   # "McDonald's Collection 2016" -> "McDonald's Promos 2016"
    "mcd17": 2148,   # "McDonald's Collection 2017" -> "McDonald's Promos 2017"
    "mcd18": 2364,   # "McDonald's Collection 2018" -> "McDonald's Promos 2018"
    "mcd19": 2555,   # "McDonald's Collection 2019" -> "McDonald's Promos 2019"
    "mcd21": 2782,   # "McDonald's Collection 2021" -> "McDonald's 25th Anniversary Promos"
    "mcd22": 3150,   # "McDonald's Collection 2022" -> "McDonald's Promos 2022"
    "tk1a": 1543,    # both EX Trainer Kit half-decks live in one TCGplayer
    "tk1b": 1543,    # group ("EX Trainer Kit 1: Latias & Latios") with
    "tk2a": 1542,    # colliding numbers — the card-name match in pick_product
    "tk2b": 1542,    # tells the half-decks apart ("EX Trainer Kit 2: Plusle & Minun")
}
# Still unmatched: "Pokémon Futsal Collection" — TCGplayer has no group for it
# at all; those cards keep the eBay fallback.

# TCGplayer group names carry a leading set code ("ME05: Pitch Black") or era
# tag ("XY - Ancient Origins", "SM - Burning Shadows")
_CODE_PREFIX_RE = re.compile(r"^[A-Za-z0-9]{1,10}(:\s*|\s+[-–—]\s+)")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_AND_RE = re.compile(r"\band\b")  # "Diamond and Pearl" ↔ "Diamond & Pearl"


# ----- Global state ----------------------------------------------------------

# The job runs as one process per day, so plain memos are enough: the groups
# list and each group's joined prices are fetched at most once per run.
_groups_cache: dict[str, int] | None = None
_prices_cache: dict[int, dict[str, list[dict]]] = {}  # groupId -> candidates_for_group

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

def _fold_ascii(text: str) -> str:
    """Accents dropped — pokemontcg.io's "Pokémon GO" must compare equal to
    TCGplayer's "Pokemon GO"."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _norm_set(name: str) -> str:
    """Comparable form of a set/group name: code/era prefix off, accents
    folded, lowercased, punctuation and "and" collapsed — "ME05: Pitch Black"/
    "Pitch Black", "XY - Ancient Origins"/"Ancient Origins", and "Diamond and
    Pearl"/"Diamond & Pearl" each normalize to the same string."""
    name = _CODE_PREFIX_RE.sub("", _fold_ascii(name).strip())
    name = _NON_ALNUM_RE.sub(" ", name.lower())
    return " ".join(_AND_RE.sub(" ", name).split())


def _norm_card_name(name: str) -> str:
    """Comparable form of a card/product name — accents folded, lowercased,
    punctuation collapsed, so "Rocket's Zapdos" matches "Rocket s Zapdos"."""
    return " ".join(_NON_ALNUM_RE.sub(" ", _fold_ascii(name).lower()).split())


def norm_number(value: str) -> str:
    """Comparable form of a card number: the part before any "/", lowercased,
    with zero-padding stripped after any letter prefix — TCGCSV's "001/084"
    matches pokemontcg.io's "1", and its "H01/H32" (e-Card holos) matches
    "H1"; suffixes ("TG12", "SWSH039") survive on both sides."""
    part = value.split("/")[0].strip().lower()
    match = re.match(r"^([a-z]*)0*(.*)$", part)
    return (match.group(1) + match.group(2)) or "0"


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


def candidates_for_group(group_id: int) -> dict[str, list[dict]]:
    """One group's card products joined product×price, keyed by normalized
    card number: {number: [{"name": product name, "prices": {variant: {...}}}]}.
    A number can carry several products — TCGplayer sells "[Staff]" prerelease
    stamps beside the regular promo under the same number, and merged groups
    (the EX Trainer Kit half-decks, WoTC promos) reuse numbers across different
    cards — so the number alone can be ambiguous; pick_product chooses. Empty
    on any failure. Fetched once per group per run."""
    cached = _prices_cache.get(group_id)
    if cached is not None:
        return cached

    products = _fetch_products(group_id)
    price_rows = _fetch_prices(group_id)
    if products is None or price_rows is None:
        return {}

    # productId -> {variant: {low, mid, high, market}} from the price rows
    variants_by_pid: dict[int, dict] = {}
    for row in price_rows:
        market, mid = row.get("marketPrice"), row.get("midPrice")
        if market is None and mid is None:
            continue  # nothing extract_price could use
        variant = {
            key: value
            for key, value in (("low", row.get("lowPrice")), ("mid", mid),
                               ("high", row.get("highPrice")), ("market", market))
            if value is not None
        }
        variants_by_pid.setdefault(row.get("productId"), {}).setdefault(
            _variant_key(row.get("subTypeName") or "Normal"), variant)

    # products without a Number extendedData entry are sealed/non-card items
    # and get skipped; ones without a usable price row contribute nothing
    joined: dict[str, list[dict]] = {}
    for product in products:
        prices = variants_by_pid.get(product.get("productId"))
        if not prices:
            continue
        for entry in product.get("extendedData") or []:
            if entry.get("name") == "Number" and entry.get("value"):
                joined.setdefault(norm_number(entry["value"]), []).append(
                    {"name": product.get("name") or "", "prices": prices})
                break

    _prices_cache[group_id] = joined
    return joined


def pick_product(candidates: list[dict] | None, card_name: str | None = None,
                 require_name: bool = False) -> dict | None:
    """The prices block of the product that IS the asked-for card, from the
    candidates sharing its number. Product names look like "Charizard -
    SWSH066 (Prerelease) [Staff]": prefer the ones whose base name (before the
    " - <number>" tail) matches the card's, then the ones without a bracketed
    qualifier (the [Staff]/[Winner] stamps are different, rarer physical cards),
    then the shortest name — so the plain version wins deterministically
    instead of whichever product the price file listed first. `require_name`
    returns None when no candidate matches the card name — for callers about
    to OVERRIDE a real price, where a number-only match isn't evidence enough."""
    if not candidates:
        return None
    pool = candidates
    if card_name:
        wanted = _norm_card_name(card_name)
        named = [c for c in pool
                 if _norm_card_name(c["name"].split(" - ")[0]) == wanted]
        if named:
            pool = named
        elif require_name:
            return None
    plain = [c for c in pool if "[" not in c["name"]]
    pool = plain or pool
    return min(pool, key=lambda c: (len(c["name"]), c["name"]))["prices"]


def prices_for_group(group_id: int) -> dict[str, dict]:
    """One group's card prices keyed by normalized card number:
    {number: {variant: {low, mid, high, market}}}, duplicate-numbered products
    resolved to the base product (pick_product without a name). Empty on any
    failure."""
    return {
        number: pick_product(candidates)
        for number, candidates in candidates_for_group(group_id).items()
    }


def card_prices(set_id: str | None, set_name: str | None, number: str | None,
                card_name: str | None = None) -> dict | None:
    """A `tcgplayer.prices`-shaped dict for one card, or None if TCGCSV can't
    match its set or number. Pass the card's name whenever it's known — it
    disambiguates numbers that several products share."""
    if not number:
        return None
    group_id = group_id_for_set(set_name, set_id)
    if group_id is None:
        return None
    return pick_product(
        candidates_for_group(group_id).get(norm_number(number)), card_name)
