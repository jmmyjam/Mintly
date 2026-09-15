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
        print("  FETCH FAILED — eBay served a bot challenge, or the network is down.")
        print("  This is a `failed fetch` in the summary; 5 in a row stop the pass.")
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
