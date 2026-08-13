"""eBay sold-listings price estimate for cards the Pokemon TCG API can't price.

The newest sets (2026 "Mega Evolution" era) carry no TCGPlayer data upstream, so
for those we estimate a market value from recent *sold* eBay listings: scrape the
completed-and-sold search, keep the most recent ungraded single-card sales, and
report their median/average.

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

# Graded slabs, lots, proxies, and "pick your card" listings aren't comparable to a
# single raw card — drop them by title (substring match on the lowercased title).
_EXCLUDE_TERMS = (
    "psa", "bgs", "cgc", "sgc", "tag ", "graded", " grade", "gem mint",
    "choose", "lot of", "bundle", "playset", "proxy", "custom", "sealed",
    "jumbo", "oversized", "sticker", "digital", "you pick", "pick your",
    "your choice", "read desc",
)

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


# ----- Query building --------------------------------------------------------

def build_query(name: str, number: str | None, set_name: str | None) -> str:
    """A specific-enough eBay keyword string for one card.

    Card numbers like "199/165" pin the exact card; when only a bare number is
    known, the set name disambiguates. Graded slabs are excluded up front too.
    """
    parts = [name.strip()]
    if number:
        parts.append(number)
    elif set_name:
        parts.append(set_name)
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

def parse_sold(html: str) -> list[dict]:
    """Recent single-card sold listings, newest first: [{date, price, title}]."""
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
        if not title or any(term in title.lower() for term in _EXCLUDE_TERMS):
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

def estimate(name: str, number: str | None, set_name: str | None) -> dict:
    query = build_query(name, number, set_name)
    cached = _cache.get(query)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    html = _fetch_sold_html(query)
    result = summarize(parse_sold(html), query) if html else summarize([], query)
    _cache[query] = (time.time(), result)
    return result
