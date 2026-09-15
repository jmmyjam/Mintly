"""eBay sold-listings price estimate for cards the Pokemon TCG API can't price.

The newest sets (2026 "Mega Evolution" era) carry no TCGPlayer data upstream, so
for those we estimate a market value from recent *sold* eBay listings: scrape the
completed-and-sold search, keep the most recent ungraded single-card sales, and
report their median/average.

The same machinery prices **slabs**: TCGplayer quotes raw singles only, so a
graded lot's market has to come from sold comps for that exact (card, grader,
grade). Passing grading/grade to estimate() searches for those slabs and keeps
only titles naming that grade, instead of discarding every graded sale.

This is best-effort and deliberately fault-tolerant — eBay markup changes and bot
checks are expected, so every failure path returns an empty estimate rather than
raising, and callers treat "no estimate" as normal.
"""
import os
import re
import time
from datetime import datetime
from statistics import mean, median

import certifi
import requests
from dotenv import load_dotenv

load_dotenv()

# ----- Configuration ---------------------------------------------------------

# Completed + sold, sorted by most-recently-ended, 60 per page
_SEARCH_URL = "https://www.ebay.com/sch/i.html"
_SEARCH_PARAMS = {"LH_Complete": "1", "LH_Sold": "1", "_sop": "13", "_ipg": "60"}

# eBay Partner Network click tagging — appended to every source_url the
# frontend renders as "View on eBay"/"Search eBay". Unset/empty = untagged
# plain URLs (the pre-affiliate behavior).
_EPN_CAMPAIGN_ID = os.getenv("EBAY_EPN_CAMPAIGN_ID", "").strip()
_EPN_PARAMS = {"mkcid": "1", "mkrid": "711-53200-19255-0",  # US ebay.com rotation
               "siteid": "0", "mkevt": "1", "toolid": "10001"}

# The user asked for recent sales, not old ones: only the newest N sold comps feed
# the estimate (eBay already returns them newest-first).
_RECENT_WINDOW = 25
_MIN_SALES = 3

_CACHE_TTL = 43200  # 12h — sold comps move slowly and scraping is expensive/fragile
_TIMEOUT = (5, 30)

# Lots, proxies, and "pick your card" listings aren't a single card at any
# condition — drop them by title (substring match on the lowercased title) in
# both raw and graded mode. The second row was added after a live sold-search
# for a graded Charizard returned a PSA-slabbed booster PACK, replica keychains,
# and a three-card "trio set" alongside the real comps.
_NOT_A_SINGLE_CARD = (
    "choose", "lot of", "bundle", "playset", "proxy", "custom", "sealed",
    "jumbo", "oversized", "sticker", "digital", "you pick", "pick your",
    "your choice", "read desc",
    "booster pack", "booster box", "replica", "keychain", "trio set",
    "elite trainer", "binder", "coin", "pin ",
)

# A slab isn't comparable to a raw card, so these drop a listing in RAW mode
# only. In graded mode the opposite holds: the title has to name the grader and
# grade we asked for (see title_matches_grade), so this list stays out of it.
# SGC stays here though Mintly no longer offers it as a holding type: an SGC slab
# is still not a raw comp.
_GRADED_TERMS = (
    "psa", "bgs", "cgc", "sgc", "graded", " grade", "gem mint",
)

# "TAG" is both a grading company and half of Pokemon's own TAG TEAM card
# subtype, so the bare substring this list used to carry dropped every genuine
# comp for a TAG TEAM card. Only TAG followed by a grade (or "grading") is the
# grader.
_TAG_SLAB_RE = re.compile(r"\btag\s*-?\s*(?:\d|grading)")

_EXCLUDE_TERMS = _GRADED_TERMS + _NOT_A_SINGLE_CARD  # raw mode: both apply (plus _TAG_SLAB_RE)

_PRICE_RE = re.compile(r"\$([\d,]+\.\d{2})")
_SOLD_RE = re.compile(r"Sold\s+([A-Z][a-z]{2}\s+\d{1,2},?\s+\d{4})")

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


# ----- Global state ----------------------------------------------------------

_cache: dict[str, tuple[float, dict]] = {}

_session = requests.Session()
_session.verify = certifi.where()
_session.headers.update({
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})


# ----- Graded (slab) matching ------------------------------------------------

# The graders whose slabs have a market of their own, mapped to the token that
# appears in a listing title. The portfolio's "Other" grading is free text with
# no reliable title form, so those lots stay unpriced (valued at cost).
_GRADERS = {"PSA": "psa", "BGS": "bgs", "CGC": "cgc", "TAG": "tag"}

# Tiers a bare number doesn't capture: a BGS 10 Black Label (all four subgrades
# 10) and a CGC Pristine 10 trade well above a plain 10 of the same card, so the
# qualifier must match in BOTH directions — a qualified want needs the words in
# the title, an unqualified want rejects a title carrying them. Scoped per grader
# because "pristine" is also plain English: in a PSA title it's a seller
# adjective ("pristine condition"), in a CGC title it's the tier name.
_GRADER_QUALIFIER = {"BGS": "black label", "CGC": "pristine"}

_QUALIFIER_RE = re.compile(r"\(([^)]*)\)")
_NUMERIC_GRADE_RE = re.compile(r"\d{1,2}(?:\.\d)?")

# What may sit between grader and grade. Titles write it every way — "PSA10",
# "PSA 10", "PSA-10", "CGC Pristine 10", "BGS GEM MT 9.5" — but the filler is
# always grading vocabulary. Allowing arbitrary characters instead would read
# "PSA Pikachu 10" (a graded card whose title never states the grade) as a 10.
_FILLER = r"(?:gem|mint|mt|gm|pristine|black|label|nm|graded|auth|authentic)"
_SEP = r"[\s\-.:#]*"
_GAP = rf"{_SEP}(?:{_FILLER}{_SEP})*"


def split_grade(grade: str) -> tuple[str, str | None]:
    """Split a stored grade into its number and qualifier.

    "10 (Black Label)" -> ("10", "black label"); "9.5" -> ("9.5", None). Mirrors
    the GRADE_OPTIONS shape in Frontend/mintly/src/grading.ts.
    """
    found = _QUALIFIER_RE.search(grade)
    return _QUALIFIER_RE.sub("", grade).strip(), (found.group(1).strip().lower() if found else None)


def _grade_number_re(number: str) -> str:
    """A grade number that can't match inside a longer figure.

    Without the guards, "9" matches the 9 in "9.5" and the tail of "19", and "10"
    matches the head of "100" — each of which prices a slab off the wrong comps.
    The "/" guards keep a card number out of it: a grade is never written
    "10/102", so a slash on either side means we're looking at the card's number.
    A trailing period is still fine ("... PSA 10. Mint").
    """
    return rf"(?<!\d)(?<!\d\.)(?<!/){re.escape(number)}(?!\d)(?!\.\d)(?!/)"


def _claimed_grades(title_low: str, token: str) -> list[str]:
    """Every grade the title claims for one grader, e.g. "PSA 9 + PSA 10" -> 9, 10."""
    return re.findall(rf"\b{token}{_GAP}({_NUMERIC_GRADE_RE.pattern})", title_low)


def title_matches_grade(title: str, grading: str, grade: str) -> bool:
    """Does this sold listing's title describe the exact slab we're pricing?

    Deliberately strict: a wrong match here silently values a holding off another
    grade's comps, which is worse than the no-estimate fallback (at cost).
    """
    token = _GRADERS.get(grading)
    if not token or not grade:
        return False
    low = title.lower()
    if token not in low:
        return False

    number, qualifier = split_grade(grade)
    tier = _GRADER_QUALIFIER.get(grading)
    if tier and (qualifier == tier) != (tier in low):
        return False

    if not _NUMERIC_GRADE_RE.fullmatch(number):
        # A non-numeric grade ("Authentic"): the word must appear, and the title
        # must not also claim a numeric grade from the same grader.
        return number.lower() in low and not _claimed_grades(low, token)

    # Grader first, grade second. The reverse reading ("GEM MINT 10 PSA") is rare
    # in real titles and would let a year prefix stand in for the grade — "1999
    # Charizard PSA" would price as a 9.
    if not re.search(rf"\b{token}{_GAP}{_grade_number_re(number)}", low):
        return False
    # A title naming another grade for this grader is a multi-slab listing, not a
    # comp for ours ("PSA 9 & PSA 10 pair").
    return all(float(claimed) == float(number) for claimed in _claimed_grades(low, token))


# ----- Card identity ---------------------------------------------------------

# eBay keyword search is loose: a live sold-search for "Charizard 4/102 PSA 10"
# came back with Japanese VMAX Climax Charizards, a Team Rocket #4/82, a Chansey,
# and a 1999 Base Set Shadowless — 60 sales spanning $19.99 to $997,512.84 around
# a $564.50 median, with only 19 of them inside ±25% of it. Grade matching alone
# can't fix that: these are all genuine PSA 10s of the wrong card. So a graded
# comp must also look like OUR card.
#
# Deliberately NOT applied to raw estimates: the same looseness is there, but
# turning this on would move every eBay-estimated price already on the site. That
# is its own change, with its own before/after.

_YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")


def _number_res(number: str) -> list[re.Pattern]:
    """Title forms of a collector number.

    Sellers write it two ways: with the set total ("4/102", sometimes "#4/102")
    or on its own ("#4"). The first is by far the more common, and getting it
    wrong is expensive — an earlier version accepted only the "#4" form and
    threw away 10 of 14 genuine comps in the live corpus.

    A **bare** "4" is never accepted: it collides with the grade itself (a card
    numbered 10 would match the "10" in every "PSA 10" title), so the number has
    to be anchored by a "#" or a "/total".

    Callers should pass the full "4/102" form when the set total is known (see
    _graded_card_meta) — then the denominator is matched exactly and a "#4/82"
    from another set can't get in. With a bare number the denominator is left
    open and the year check is what separates same-numbered reprints.
    """
    number = number.strip()
    base = number.split("/")[0]
    if not base.isdigit():
        return []
    pats = []
    if "/" in number:
        # Exact: "4/102" / "#4/102", not "104/102" and not "4/1020"
        pats.append(re.compile(rf"(?<!\d)#?\s*{re.escape(number)}(?!\d)"))
    else:
        # Set total unknown: accept any denominator ("4/102", "4/108"…)
        pats.append(re.compile(rf"(?<!\d)#?\s*{re.escape(base)}/\d{{1,4}}"))
    # "#4" standing alone — never with a denominator after it, or "#4/82" (a
    # different set's card 4) would pass. Our own "#4/102" is already covered by
    # the slash pattern above.
    pats.append(re.compile(rf"#\s*{re.escape(base)}(?![\d/])"))
    return pats


def title_matches_card(title: str, number: str | None, year: int | None) -> bool:
    """Is this listing plausibly OUR card, not just something with the same name?

    Two cheap signals that between them split the common confusions: the
    collector number (wrong card in another set) and the print year (a reprint of
    the same number — 1999 Base Charizard #4 vs 2021 Celebrations #4). A title
    that states no year isn't penalised; one that states a different year is.
    """
    low = title.lower()
    if number:
        pats = _number_res(number)
        if pats and not any(p.search(low) for p in pats):
            return False
    if year:
        found = [int(y) for y in _YEAR_RE.findall(low)]
        if found and year not in found:
            return False
    return True


# ----- Query building --------------------------------------------------------

def build_query(name: str, number: str | None, set_name: str | None,
                grading: str | None = None, grade: str | None = None) -> str:
    """A specific-enough eBay keyword string for one card.

    Card numbers like "199/165" pin the exact card; when only a bare number is
    known, the set name disambiguates. Raw mode excludes graded slabs up front;
    passing grading/grade flips that into a search FOR that slab ("PSA 10",
    "BGS 10 Black Label").
    """
    parts = [name.strip()]
    if number:
        parts.append(number)
    elif set_name:
        parts.append(set_name)
    if grading and grade:
        base, qualifier = split_grade(grade)
        parts += [grading, base]
        if qualifier:
            parts.append(qualifier)
    else:
        parts += ["-psa", "-bgs", "-cgc"]
    return " ".join(p for p in parts if p)


# ----- Fetch -----------------------------------------------------------------

# eBay serves a bot challenge instead of results when it doesn't trust a request.
# Two shapes seen in the wild: a tiny (~2KB) "Error Page | eBay", and a ~120KB
# "Pardon Our Interruption" JS challenge (PerimeterX/HUMAN — spinners, no
# listings). A genuine sold-results page is ~1MB+ even with zero organic results,
# so treat a page as blocked when it carries a known challenge title OR is far
# under a real page's size. The size floor is what catches future challenge
# variants whose title we don't yet know; it sits well above the ~120KB
# interruption page and well below a real page, and its only false-positive cost
# is an estimate that degrades to count:0 — the same outcome as a card with no
# comps. (A real page legitimately contains "something went wrong" buried in its
# scripts, so we never match on that.)
_BLOCK_TITLES = ("Error Page | eBay", "Pardon Our Interruption")
_MIN_REAL_PAGE_BYTES = 250_000


def _looks_blocked(html: str) -> bool:
    return (any(title in html[:2000] for title in _BLOCK_TITLES)
            or len(html) < _MIN_REAL_PAGE_BYTES)


def _fetch_sold_html(query: str) -> str | None:
    """Fetch the sold-listings HTML. eBay rejects cold requests, so seed cookies
    from the homepage first and retry once if we still get the challenge page."""
    params = {"_nkw": query, **_SEARCH_PARAMS}
    for attempt in range(2):
        try:
            if not _session.cookies or attempt == 1:
                _session.get("https://www.ebay.com/", timeout=_TIMEOUT)
            resp = _session.get(
                _SEARCH_URL, params=params, timeout=_TIMEOUT,
                headers={"Referer": "https://www.ebay.com/"},
            )
        except requests.RequestException:
            return None
        if resp.status_code == 200 and not _looks_blocked(resp.text):
            return resp.text
        _session.cookies.clear()  # force a re-seed on the retry
    return None


def search_url(query: str) -> str:
    from urllib.parse import urlencode
    params = {"_nkw": query, **_SEARCH_PARAMS}
    if _EPN_CAMPAIGN_ID:
        params.update(_EPN_PARAMS, campid=_EPN_CAMPAIGN_ID)
    return f"{_SEARCH_URL}?{urlencode(params)}"


# ----- Parse & summarize -----------------------------------------------------

def parse_sold(html: str, want: tuple[str, str] | None = None,
               identity: tuple[str | None, int | None] | None = None) -> list[dict]:
    """Recent single-card sold listings, newest first: [{date, price, title}].

    `want` is an optional (grading, grade) pair: given one, keep only listings
    whose title names that exact slab instead of dropping every graded sale.
    `identity` is an optional (number, year) pair that additionally requires the
    listing to look like our card (see title_matches_card).
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    sales = []
    for card in soup.select(".su-card-container"):
        text = card.get_text(" ", strip=True)
        sold = _SOLD_RE.search(text)
        if not sold:
            continue  # promo / "Shop on eBay" tiles carry no sold date
        img = card.select_one("img[alt]")
        title = (img.get("alt") if img else "").strip()
        low = title.lower()
        if not title or any(term in low for term in _NOT_A_SINGLE_CARD):
            continue
        if want is None:
            if any(term in low for term in _GRADED_TERMS) or _TAG_SLAB_RE.search(low):
                continue
        elif not title_matches_grade(title, *want):
            continue
        if identity and not title_matches_card(title, *identity):
            continue
        # The price after the "Sold <date>" marker is the item's own sold price
        # (a leading price could be a shipping figure or range low end).
        match = _PRICE_RE.search(text[sold.end():])
        if not match:
            continue
        try:
            when = datetime.strptime(sold.group(1).replace(",", ""), "%b %d %Y").date()
        except ValueError:
            continue
        sales.append({
            "date": when.isoformat(),
            "price": float(match.group(1).replace(",", "")),
            "title": title,
        })
    sales.sort(key=lambda s: s["date"], reverse=True)
    return sales


def summarize(sales: list[dict], query: str) -> dict:
    empty = {
        "count": 0, "median": None, "average": None, "low": None, "high": None,
        "currency": "USD", "since": None, "until": None,
        "source_url": search_url(query), "sample": [],
    }
    recent = sales[:_RECENT_WINDOW]
    if len(recent) < _MIN_SALES:
        return empty

    prices = [s["price"] for s in recent]
    med = median(prices)
    # Reject comps far off the recent median — wrong variant, damaged, or proxy
    kept = [s for s in recent if 0.35 * med <= s["price"] <= 3 * med] or recent
    kp = [s["price"] for s in kept]
    dates = [s["date"] for s in kept]
    return {
        "count": len(kept),
        "median": round(median(kp), 2),
        "average": round(mean(kp), 2),
        "low": round(min(kp), 2),
        "high": round(max(kp), 2),
        "currency": "USD",
        "since": min(dates),
        "until": max(dates),
        "source_url": search_url(query),
        "sample": kept[:6],
    }


# ----- Public API ------------------------------------------------------------

def estimate(name: str, number: str | None, set_name: str | None,
             grading: str | None = None, grade: str | None = None,
             year: int | None = None) -> dict:
    """Recent-sales estimate for a card, raw by default.

    A grading/grade pair prices that slab instead: a different search and a
    different title filter, so its cache entry is separate too (the query string
    is the key). A grading we can't search ("Other", or a missing grade) returns
    the empty estimate rather than falling back to the raw figure — a raw price
    is not a slab's value.

    `year` (the set's release year) only sharpens the graded path for now; see
    the Card identity section for why raw estimates are left as they are.
    """
    want = None
    if grading and grading != "Raw":
        if grading not in _GRADERS or not grade:
            return summarize([], build_query(name, number, set_name))
        want = (grading, grade)

    query = build_query(name, number, set_name, *(want or (None, None)))
    cached = _cache.get(query)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    identity = (number, year) if want else None
    html = _fetch_sold_html(query)
    result = (summarize(parse_sold(html, want, identity), query) if html
              else summarize([], query))
    _cache[query] = (time.time(), result)
    return result
