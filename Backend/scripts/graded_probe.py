"""Why did a slab fail to price? Shows the eBay search behind graded_fill and
which filter dropped each sold listing.

graded_fill only reports counts ("1 tried, 1 without recent comps"), which says
a slab didn't price but not whether eBay blocked us, the search returned other
cards, or the comps are genuinely too thin. This prints the whole chain.

    python scripts/graded_probe.py                 # every held graded combo
    python scripts/graded_probe.py base1-4 PSA 10  # one specific slab

Read-only: it scrapes and prints, and records nothing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal  # noqa: E402
from app.services import ebay_prices  # noqa: E402

import snapshot_all  # noqa: E402  (sibling script: held combos + catalog meta)


def diagnose_fetch(query: str) -> None:
    """Separate the three things `_fetch_sold_html` returning None can mean.

    It collapses a network error, a non-200, and a bot challenge into one None,
    which is right for the job (all three mean "no estimate") and useless when
    you're trying to work out what to do about it.
    """
    import re

    print("  --- diagnosing ---")
    # 1. Can this box reach eBay at all?
    try:
        home = ebay_prices._session.get("https://www.ebay.com/",
                                        timeout=ebay_prices._TIMEOUT)
        print(f"  homepage: HTTP {home.status_code}, {len(home.text):,} bytes")
    except Exception as exc:
        print(f"  homepage: NETWORK ERROR — {type(exc).__name__}: {exc}")
        print("  => the container can't reach eBay. Not a bot block; check "
              "outbound DNS/egress from the api container.")
        return

    # 2. What does the search itself actually return?
    params = {"_nkw": query, **ebay_prices._SEARCH_PARAMS}
    try:
        resp = ebay_prices._session.get(
            ebay_prices._SEARCH_URL, params=params,
            timeout=ebay_prices._TIMEOUT,
            headers={"Referer": "https://www.ebay.com/"},
        )
    except Exception as exc:
        print(f"  search:   NETWORK ERROR — {type(exc).__name__}: {exc}")
        return

    body = resp.text
    title = re.search(r"<title>(.*?)</title>", body, re.S)
    title = title.group(1).strip()[:90] if title else "(none)"
    print(f"  search:   HTTP {resp.status_code}, {len(body):,} bytes")
    print(f"  title:    {title!r}")

    if resp.status_code != 200:
        print(f"  => eBay refused with HTTP {resp.status_code}.")
        return
    known = [t for t in ebay_prices._BLOCK_TITLES if t in body[:2000]]
    if known:
        print(f"  => BOT CHALLENGE ({known[0]!r}). eBay does not trust this IP.")
    elif len(body) < ebay_prices._MIN_REAL_PAGE_BYTES:
        print(f"  => page is under the {ebay_prices._MIN_REAL_PAGE_BYTES:,}-byte floor "
              f"for a real results page, so it's treated as a challenge. If the "
              f"title above looks like genuine results, the floor is what's wrong, "
              f"not eBay.")
    else:
        print("  => looks like a real page; the block detector disagreed. "
              "Worth re-checking _looks_blocked against this response.")


def probe(db, card_id: str, grader: str, grade: str) -> None:
    meta = snapshot_all._graded_card_meta(db, {card_id})
    card = meta.get(card_id)
    print("=" * 78)
    print(f"{card_id}  {grader} {grade}")
    if not card:
        print("  NO CATALOG ROW — the fill counts this as unpriceable, not a failure.")
        return
    print(f"  catalog: name={card['name']!r} number={card['number']!r} "
          f"set={card['set_name']!r} year={card['year']}")
    if grader not in ebay_prices._GRADERS:
        print(f"  GRADER {grader!r} HAS NO SEARCHABLE FORM — unpriceable by design "
              f"(searchable: {', '.join(sorted(ebay_prices._GRADERS))}).")
        return

    query = ebay_prices.build_query(card["name"], card["number"], card["set_name"],
                                    grader, grade)
    print(f"  query:   {query!r}")

    html = ebay_prices._fetch_sold_html(query)
    if html is None:
        print("  FETCH FAILED — a `failed fetch` in the summary; 5 in a row stop the pass.")
        diagnose_fetch(query)
        return
    print(f"  fetched {len(html):,} bytes")

    sales = ebay_prices.parse_sold(html)  # unfiltered, to show everything
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    titles = []
    for tile in soup.select(".su-card-container"):
        if not ebay_prices._SOLD_RE.search(tile.get_text(" ", strip=True)):
            continue
        img = tile.select_one("img[alt]")
        title = (img.get("alt") if img else "").strip()
        if title:
            titles.append(title)

    kept = ebay_prices.parse_sold(html, want=(grader, grade),
                                  identity=(card["number"], card["year"]))
    kept_titles = {s["title"] for s in kept}
    print(f"  {len(titles)} sold listings on the page, {len(kept)} usable as comps")
    print(f"  (raw-mode parse would keep {len(sales)} — that filter is for ungraded)")
    print()

    for title in titles:
        low = title.lower()
        if title in kept_titles:
            reason = "KEEP"
        elif any(term in low for term in ebay_prices._NOT_A_SINGLE_CARD):
            reason = "drop: not a single card"
        elif not ebay_prices.title_matches_grade(title, grader, grade):
            reason = "drop: wrong grade"
        elif not ebay_prices.title_matches_card(title, card["number"], card["year"]):
            reason = "drop: wrong card"
        else:
            reason = "drop: ?"
        print(f"   [{reason:26}] {title[:90]}")

    est = ebay_prices.summarize(kept, query)
    print()
    print(f"  => count={est['count']} median={est['median']} "
          f"low={est['low']} high={est['high']}")
    if est["count"] == 0:
        print(f"  Nothing recorded: needs at least {ebay_prices._MIN_SALES} comps.")
        print("  If the drops above look wrong, the filters are too strict for "
              "this card — check the number/year the catalog gave us.")


def main() -> int:
    db = SessionLocal()
    try:
        if len(sys.argv) == 4:
            combos = [(sys.argv[1], sys.argv[2], sys.argv[3])]
        else:
            combos = snapshot_all.held_graded_combos(db)
            if not combos:
                print("No graded lots held — nothing for graded_fill to price.")
                return 0
            print(f"{len(combos)} held graded combo(s)\n")
        for card_id, grader, grade in combos:
            probe(db, card_id, grader, grade)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
