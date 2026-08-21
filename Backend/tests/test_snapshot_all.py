"""snapshot_all's crawl: pages that fail their inline retries are remembered and
re-tried in an end-of-run second pass; only a page failing both passes marks the
run incomplete (and never aborts the crawl). Cards with no TCGPlayer price get a
capped eBay-estimate pass (newest sets first) instead of being skipped."""
import os
import sys

import pytest

# the script lives outside the app package, so put scripts/ on the path
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import snapshot_all
from app.models import CardPriceSnapshot
from app.services import card_catalog
from conftest import TestingSessionLocal, make_card


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FlakyUpstream:
    """Serves paged cards; page N fails its first fail_first[N] requests."""

    def __init__(self, pages: dict[int, list], fail_first: dict[int, int]):
        self.pages = pages
        self.fail_first = fail_first
        self.hits: dict[int, int] = {}

    def get(self, url, params=None, timeout=None):
        page = params["page"]
        self.hits[page] = self.hits.get(page, 0) + 1
        if self.hits[page] <= self.fail_first.get(page, 0):
            return FakeResponse(404, {"error": "transient flake"})
        total = sum(len(cards) for cards in self.pages.values())
        return FakeResponse(200, {"data": self.pages.get(page, []),
                                  "totalCount": total})


def three_pages() -> dict[int, list]:
    return {p: [make_card(f"c{p}-{i}", price=float(p * 10 + i)) for i in range(2)]
            for p in (1, 2, 3)}


@pytest.fixture
def crawl(monkeypatch):
    """2-card pages so the fake crawl is 3 pages; no real sleeping."""
    monkeypatch.setattr(snapshot_all, "_PAGE_SIZE", 2)
    monkeypatch.setattr(snapshot_all.time, "sleep", lambda s: None)

    def run(fail_first: dict[int, int]):
        fake = FlakyUpstream(three_pages(), fail_first)
        monkeypatch.setattr(snapshot_all, "session", fake)
        return snapshot_all.fetch_all_prices()

    return run


def test_clean_crawl_is_complete(crawl):
    result = crawl({})
    assert result.complete
    assert len(result.prices) == 6
    assert result.recovered == [] and result.dropped == []


def test_failed_page_recovered_by_end_of_run_retry(crawl):
    # page 2 fails all inline retries, then succeeds in the retry pass
    result = crawl({2: snapshot_all._MAX_RETRIES})
    assert result.complete  # recovered, so the run is NOT incomplete
    assert result.recovered == [2]
    assert len(result.prices) == 6
    assert "c2-0" in result.prices


def test_page_failing_every_pass_marks_incomplete(crawl):
    result = crawl({3: 99})  # page 3 never succeeds
    assert not result.complete
    assert result.dropped == [3]
    assert len(result.prices) == 4  # the other pages were still collected
    assert "c3-0" not in result.prices


def test_page_recovered_by_a_later_retry_sweep(crawl):
    # fails the 3 inline attempts AND the first end-of-run sweep, then succeeds
    # on the second sweep — a longer flake burst still mustn't drop the page
    result = crawl({2: snapshot_all._MAX_RETRIES + 1})
    assert result.complete
    assert result.recovered == [2]
    assert "c2-0" in result.prices


# ---- Catalog upsert + sync marker -------------------------------------------
# The crawl mirrors every card into card_catalog; only a complete, un-truncated
# run may stamp the sync marker that lets list endpoints trust the catalog.

@pytest.fixture
def run_main(monkeypatch):
    monkeypatch.setattr(snapshot_all, "_PAGE_SIZE", 2)
    monkeypatch.setattr(snapshot_all.time, "sleep", lambda s: None)
    monkeypatch.setattr(snapshot_all, "SessionLocal", TestingSessionLocal)
    # no set resolves by default — keeps the tcgcsv fill and the price sanity
    # check off the network; fake_tcgcsv re-patches this for its one set
    monkeypatch.setattr(snapshot_all.tcgcsv, "group_id_for_set",
                        lambda name, set_id=None: None)
    # every image URL verifies clean by default — keeps the image check off
    # the network; the image-check tests re-patch this
    monkeypatch.setattr(snapshot_all, "_head_image", lambda url: 200)

    def run(extra_args: list[str] = [], fail_first: dict[int, int] = {},
            pages: dict[int, list] | None = None):
        fake = FlakyUpstream(pages or three_pages(), fail_first)
        monkeypatch.setattr(snapshot_all, "session", fake)
        monkeypatch.setattr(sys, "argv", ["snapshot_all.py", "--max-ebay", "0",
                                          "--no-archive", *extra_args])
        return snapshot_all.main()

    return run


def test_complete_run_fills_catalog_and_stamps_sync(run_main):
    assert run_main() == 0
    db = TestingSessionLocal()
    try:
        assert card_catalog.is_synced(db)
        envelope, _ = card_catalog.search(db, name="Test Card")
        assert envelope["totalCount"] == 6
        assert card_catalog.get_card(db, "c2-1").data["tcgplayer"]  # full dict stored
    finally:
        db.close()


def test_max_pages_smoke_run_never_stamps_sync(run_main):
    assert run_main(["--max-pages", "2"]) == 0
    db = TestingSessionLocal()
    try:
        assert not card_catalog.is_synced(db)          # truncated ≠ complete
        assert card_catalog.get_card(db, "c1-0") is not None  # but cards landed
    finally:
        db.close()


def test_incomplete_crawl_never_stamps_sync(run_main):
    assert run_main(fail_first={3: 99}) == 0  # page 3 dropped both passes
    db = TestingSessionLocal()
    try:
        assert not card_catalog.is_synced(db)
        assert card_catalog.get_card(db, "c1-0") is not None
    finally:
        db.close()


# ---- eBay fill for cards TCGPlayer can't price ------------------------------

def mega_card(card_id: str = "me9-1", number: str = "188",
              name: str = "Mega Card ex") -> dict:
    """An upstream card dict with NO TCGPlayer prices (newest-set style)."""
    return {"id": card_id, "name": name, "number": number,
            "set": {"id": "me9", "name": "Mega Set",
                    "releaseDate": "2026/05/30"}}


def test_crawl_collects_unpriced_card_metadata(crawl, monkeypatch):
    pages = three_pages()
    pages[2][0] = mega_card()
    fake = FlakyUpstream(pages, {})
    monkeypatch.setattr(snapshot_all, "session", fake)
    result = snapshot_all.fetch_all_prices()

    assert "me9-1" not in result.prices
    assert result.unpriced == [{
        "id": "me9-1", "name": "Mega Card ex", "number": "188",
        "set_id": "me9", "set_name": "Mega Set", "release": "2026/05/30",
    }]


def unpriced(card_id: str, release: str = "2026/05/30") -> dict:
    # name doubles as the estimator-call key in FakeEstimator
    return {"id": card_id, "name": card_id, "number": "1",
            "set_name": "Some Set", "release": release}


class FakeEstimator:
    """_estimate_one stand-in: medians keyed by card name; names in `failing`
    simulate a failed fetch (None), anything else a fetched-but-saleless page."""

    def __init__(self, medians: dict[str, float], failing: set[str] = frozenset()):
        self.medians = medians
        self.failing = failing
        self.calls: list[str] = []

    def __call__(self, card):
        name = card["name"]
        self.calls.append(name)
        if name in self.failing:
            return None
        med = self.medians.get(name)
        return {"count": 5 if med else 0, "median": med}


@pytest.fixture
def fill(monkeypatch):
    """Run ebay_fill against the test DB with a fake estimator; no real sleeping."""
    monkeypatch.setattr(snapshot_all.time, "sleep", lambda s: None)

    def run(cards: list[dict], medians: dict[str, float], budget: int,
            failing: set[str] = frozenset()):
        fake = FakeEstimator(medians, failing)
        monkeypatch.setattr(snapshot_all, "_estimate_one", fake)
        db = TestingSessionLocal()
        try:
            return snapshot_all.ebay_fill(db, cards, budget), fake
        finally:
            db.close()

    return run


def test_ebay_fill_prices_newest_sets_first_within_budget(fill):
    cards = [unpriced("old-1", "2001/01/01"),
             unpriced("new-1", "2026/07/01"),
             unpriced("mid-1", "2024/06/15")]
    result, fake = fill(cards, {"new-1": 250.0, "mid-1": 12.5, "old-1": 3.0}, budget=2)

    assert fake.calls == ["new-1", "mid-1"]  # newest first, old-1 beyond budget
    assert result.prices == {"new-1": 250.0, "mid-1": 12.5}
    assert result.attempted == 2
    assert result.eligible == 3


def test_ebay_fill_skips_cards_already_snapshotted_today(fill):
    db = TestingSessionLocal()
    db.add(CardPriceSnapshot(card_id="done-1", price=9.99))
    db.commit()
    db.close()

    result, fake = fill([unpriced("done-1"), unpriced("todo-1")],
                        {"done-1": 1.0, "todo-1": 2.0}, budget=10)

    assert fake.calls == ["todo-1"]  # no scrape wasted on the already-recorded card
    assert result.prices == {"todo-1": 2.0}
    assert result.eligible == 1


def test_ebay_fill_saleless_cards_record_nothing_but_never_stop_the_pass(fill, monkeypatch):
    # cards with no recent comps are normal deep in the unpriced tail — the pass
    # must keep going through them, not mistake them for a block
    monkeypatch.setattr(snapshot_all, "_EBAY_GIVEUP", 3)
    cards = [unpriced(f"nosales-{i}") for i in range(10)]
    result, fake = fill(cards, {}, budget=10)

    assert result.prices == {}
    assert result.attempted == 10  # all tried, well past the give-up threshold
    assert result.no_sales == 10
    assert not result.gave_up


def test_ebay_fill_gives_up_after_consecutive_failed_fetches(fill, monkeypatch):
    monkeypatch.setattr(snapshot_all, "_EBAY_GIVEUP", 3)
    cards = [unpriced(f"blocked-{i}") for i in range(10)]
    result, fake = fill(cards, {}, budget=10,
                        failing={c["name"] for c in cards})

    assert result.gave_up
    assert result.attempted == 3  # stopped at the give-up threshold, not the budget
    assert result.failures == 3
    assert result.prices == {}


def test_ebay_fill_successful_fetch_resets_the_failure_streak(fill, monkeypatch):
    monkeypatch.setattr(snapshot_all, "_EBAY_GIVEUP", 3)
    cards = [unpriced(f"c-{i}") for i in range(6)]
    # fail, fail, ok, fail, fail, ok — never 3 in a row
    failing = {"c-0", "c-1", "c-3", "c-4"}
    result, fake = fill(cards, {"c-2": 5.0, "c-5": 7.0}, budget=10, failing=failing)

    assert not result.gave_up
    assert result.attempted == 6
    assert result.failures == 4
    assert result.prices == {"c-2": 5.0, "c-5": 7.0}


# ---- TCGCSV fill for cards TCGPlayer can't price ----------------------------
# Real TCGplayer prices from the TCGCSV mirror are injected into the card dicts
# BEFORE the catalog upsert (so they're stored like any upstream price) and
# BEFORE the eBay pass (which only sees what TCGCSV couldn't match).

def crawl_with(*cards: dict) -> "snapshot_all.Crawl":
    """A Crawl holding unpriced cards, shaped the way _collect builds them."""
    return snapshot_all.Crawl(cards=list(cards), unpriced=[
        {"id": c["id"], "name": c["name"], "number": c["number"],
         "set_id": c["set"]["id"], "set_name": c["set"]["name"],
         "release": c["set"]["releaseDate"]}
        for c in cards
    ])


@pytest.fixture
def fake_tcgcsv(monkeypatch):
    """A one-set fake mirror: "Mega Set" resolves, card number 188 is priced."""
    monkeypatch.setattr(
        snapshot_all.tcgcsv, "group_id_for_set",
        lambda name, set_id=None: 24380 if name == "Mega Set" else None)
    monkeypatch.setattr(
        snapshot_all.tcgcsv, "candidates_for_group",
        lambda gid: {"188": [{"name": "Mega Card ex - 188/132",
                              "prices": {"holofoil": {"market": 250.0,
                                                      "mid": 260.0}},
                              "image": "https://cdn.example/product/9_200w.jpg",
                              "productId": 9}]})


def test_tcgcsv_fill_injects_prices_and_shrinks_the_ebay_set(fake_tcgcsv):
    card = mega_card()
    crawl = crawl_with(card)
    result = snapshot_all.tcgcsv_fill(crawl)

    # real prices injected into the full card dict (what the catalog stores),
    # marked so the request-path refresh can't overwrite them with upstream's
    assert card["tcgplayer"]["prices"]["holofoil"]["market"] == 250.0
    assert card["tcgplayer"]["priceSource"] == "tcgcsv"
    # a direct product url rides along — the CardDetail buy link reads it
    assert card["tcgplayer"]["url"] == "https://www.tcgplayer.com/product/9"
    # snapshot price is extract_price of the injected block
    assert result.prices == {"me9-1": 250.0}
    assert result.sets_matched == 1 and result.sets_unmatched == []
    # the eBay candidate computation drops the matched card
    assert [c for c in crawl.unpriced if c["id"] not in result.prices] == []


def test_tcgcsv_fill_preserves_an_existing_url(fake_tcgcsv):
    # upstream's own url (the prices.pokemontcg.io redirect) wins when present —
    # the fill only adds a product url to cards that have none
    card = mega_card()
    card["tcgplayer"] = {"url": "https://prices.pokemontcg.io/tcgplayer/me9-1"}
    snapshot_all.tcgcsv_fill(crawl_with(card))

    assert card["tcgplayer"]["url"] == "https://prices.pokemontcg.io/tcgplayer/me9-1"
    assert card["tcgplayer"]["prices"]["holofoil"]["market"] == 250.0
    assert card["tcgplayer"]["priceSource"] == "tcgcsv"


def test_tcgcsv_fill_misses_leave_cards_for_ebay(fake_tcgcsv):
    unmatched_set = mega_card("xx1-1")
    unmatched_set["set"] = {"id": "xx1", "name": "Unknown Set",
                            "releaseDate": "2001/01/01"}
    missed_number = mega_card("me9-2", number="999", name="Missed Card")
    crawl = crawl_with(unmatched_set, missed_number)
    result = snapshot_all.tcgcsv_fill(crawl)

    assert result.prices == {}
    assert result.sets_matched == 1          # Mega Set matched, just not #999
    assert result.sets_unmatched == ["Unknown Set"]
    assert "tcgplayer" not in unmatched_set and "tcgplayer" not in missed_number
    remaining = [c for c in crawl.unpriced if c["id"] not in result.prices]
    assert {c["id"] for c in remaining} == {"xx1-1", "me9-2"}


def test_tcgcsv_fill_survives_service_errors(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("mirror exploded")
    monkeypatch.setattr(snapshot_all.tcgcsv, "group_id_for_set", boom)
    result = snapshot_all.tcgcsv_fill(crawl_with(mega_card()))

    assert result.prices == {}
    assert result.sets_unmatched == ["Mega Set"]


def test_tcgcsv_priced_card_lands_in_catalog_and_history(run_main, fake_tcgcsv):
    # ordering guarantee: inject BEFORE upsert, so the catalog row carries the
    # real prices and the day's snapshot matches them
    pages = three_pages()
    pages[2][0] = mega_card()
    assert run_main(pages=pages) == 0

    db = TestingSessionLocal()
    try:
        stored = card_catalog.get_card(db, "me9-1").data
        assert stored["tcgplayer"]["prices"]["holofoil"]["market"] == 250.0
        # the injected product url lands in the catalog with the prices
        assert stored["tcgplayer"]["url"] == "https://www.tcgplayer.com/product/9"
        snap = (db.query(CardPriceSnapshot)
                  .filter(CardPriceSnapshot.card_id == "me9-1").one())
        assert snap.price == 250.0
    finally:
        db.close()


def test_ebay_pass_only_sees_cards_tcgcsv_missed(run_main, monkeypatch, fake_tcgcsv):
    pages = three_pages()
    pages[2][0] = mega_card()                                    # TCGCSV covers
    pages[3][0] = mega_card("me9-2", number="999", name="Missed Card")
    estimator = FakeEstimator({"Missed Card": 40.0})
    monkeypatch.setattr(snapshot_all, "_estimate_one", estimator)
    assert run_main(["--max-ebay", "5"], pages=pages) == 0

    assert estimator.calls == ["Missed Card"]  # never the TCGCSV-priced card
    db = TestingSessionLocal()
    try:
        snap = (db.query(CardPriceSnapshot)
                  .filter(CardPriceSnapshot.card_id == "me9-2").one())
        assert snap.price == 40.0
    finally:
        db.close()


def test_no_tcgcsv_flag_skips_the_fill(run_main, monkeypatch):
    called = []
    monkeypatch.setattr(snapshot_all, "tcgcsv_fill",
                        lambda crawl: called.append(1) or snapshot_all.TcgcsvFill())
    pages = three_pages()
    pages[2][0] = mega_card()
    assert run_main(["--no-tcgcsv"], pages=pages) == 0
    assert called == []


# ---- Stamp/mark varieties forked into their own cards -----------------------
# A card number can carry several TCGplayer products (the regular card plus a
# [Staff] stamp, error print, ...). variety_fill forks each stamped/marked
# sibling into its own synthetic catalog card, searchable + snapshotted like any
# card. Finishes (sub-types of one product) never fork.

@pytest.fixture
def fake_variety_mirror(monkeypatch):
    """A one-set mirror where number 188 has the regular card AND a [Staff]
    stamp under the same number."""
    monkeypatch.setattr(
        snapshot_all.tcgcsv, "group_id_for_set",
        lambda name, set_id=None: 24380 if name == "Mega Set" else None)
    monkeypatch.setattr(
        snapshot_all.tcgcsv, "candidates_for_group",
        lambda gid: {"188": [
            {"name": "Mega Card ex - 188/132",
             "prices": {"holofoil": {"market": 250.0, "mid": 260.0}},
             "image": "https://cdn.example/product/9_200w.jpg", "productId": 9},
            {"name": "Mega Card ex - 188/132 [Staff]",
             "prices": {"holofoil": {"market": 900.0, "mid": 950.0}},
             "image": "https://cdn.example/product/10_200w.jpg", "productId": 10},
        ]})


def test_variety_fill_forks_the_stamp(fake_variety_mirror):
    base = mega_card()
    result = snapshot_all.variety_fill(crawl_with(base))

    assert len(result.cards) == 1
    v = result.cards[0]
    assert v["id"] == "me9-1~v10"                      # base id + productId
    assert v["name"] == "Mega Card ex [Staff]"         # number tail stripped
    assert v["varietyOf"] == "me9-1"
    assert v["number"] == "188" and v["set"]["id"] == "me9"
    assert v["tcgplayer"]["prices"]["holofoil"]["market"] == 900.0
    assert v["tcgplayer"]["priceSource"] == "tcgcsv"
    assert v["tcgplayer"]["url"] == "https://www.tcgplayer.com/product/10"
    assert v["images"]["source"] == "tcgplayer"
    assert result.prices == {"me9-1~v10": 900.0}
    # variety_fill never touches the base card (tcgcsv_fill prices that)
    assert "tcgplayer" not in base


def test_variety_lands_in_catalog_search_and_history(run_main, fake_variety_mirror):
    pages = three_pages()
    pages[2][0] = mega_card()
    assert run_main(pages=pages) == 0

    db = TestingSessionLocal()
    try:
        row = card_catalog.get_card(db, "me9-1~v10")
        assert row is not None and row.data["varietyOf"] == "me9-1"
        assert row.data["name"] == "Mega Card ex [Staff]"
        assert row.data["tcgplayer"]["prices"]["holofoil"]["market"] == 900.0
        # both the base and its variety are searchable by the shared name
        envelope, _ = card_catalog.search(db, name="Mega Card ex")
        ids = {c["id"] for c in envelope["data"]}
        assert {"me9-1", "me9-1~v10"} <= ids
        # the variety gets its own daily snapshot
        snap = (db.query(CardPriceSnapshot)
                  .filter(CardPriceSnapshot.card_id == "me9-1~v10").one())
        assert snap.price == 900.0
    finally:
        db.close()


def test_no_tcgcsv_flag_skips_variety_fill(run_main, monkeypatch):
    called = []
    monkeypatch.setattr(snapshot_all, "variety_fill",
                        lambda crawl: called.append(1) or snapshot_all.VarietyFill())
    assert run_main(["--no-tcgcsv"]) == 0
    assert called == []


# ---- Dropped-page recovery via the catalog + TCGCSV --------------------------
# A page pokemontcg.io couldn't serve even after the retry pass leaves its cards
# out of the crawl entirely, so the tcgcsv/eBay fills (driven by crawl.unpriced)
# never see them. recover_dropped pulls those cards from the catalog and prices
# them from the independent TCGCSV mirror, so the outage doesn't gap history.

def test_recover_dropped_prices_uncrawled_catalog_cards_via_tcgcsv(fake_tcgcsv):
    db = TestingSessionLocal()
    try:
        # the catalog already holds two Mega Set cards from a prior sync
        card_catalog.upsert_cards(db, [mega_card("me9-1", "1"),
                                       mega_card("me9-2", "188")])
        # this run crawled only me9-1; me9-2's page dropped both passes
        crawl = snapshot_all.Crawl(cards=[mega_card("me9-1", "1")], dropped=[7])
        result = snapshot_all.recover_dropped(db, crawl)

        assert result.candidates == 1              # only me9-2 was uncrawled
        assert result.prices == {"me9-2": 250.0}   # priced from the TCGCSV mirror
        assert "me9-1" not in result.prices        # the crawled card is left alone
        # dropped-page cards get the product url injected too
        recovered = next(c for c in result.cards if c["id"] == "me9-2")
        assert recovered["tcgplayer"]["url"] == "https://www.tcgplayer.com/product/9"
    finally:
        db.close()


def test_dropped_page_cards_recovered_from_catalog_via_tcgcsv(run_main, fake_tcgcsv):
    # a card the catalog knows from a prior sync, whose page drops this run, is
    # priced from TCGCSV instead of vanishing from history for the day
    db = TestingSessionLocal()
    card_catalog.upsert_cards(db, [mega_card("me9-1", "188")])
    card_catalog.mark_full_sync(db)
    db.close()

    # page 3 drops both passes; me9-1 is on no page this run
    assert run_main(fail_first={3: 99}) == 0

    db = TestingSessionLocal()
    try:
        snap = (db.query(CardPriceSnapshot)
                  .filter(CardPriceSnapshot.card_id == "me9-1").one())
        assert snap.price == 250.0   # recovered from the TCGCSV mirror
        # its catalog price was refreshed too
        assert card_catalog.get_card(db, "me9-1").data["tcgplayer"]["prices"]
    finally:
        db.close()


def test_recovery_skipped_until_catalog_synced(run_main, monkeypatch):
    # a first-ever run has no catalog universe to diff against — a dropped page's
    # never-seen cards can't be recovered yet, so the stage stays off
    called = []
    monkeypatch.setattr(snapshot_all, "recover_dropped",
                        lambda db, crawl: called.append(1) or snapshot_all.DroppedFill())
    assert run_main(fail_first={3: 99}) == 0  # fresh DB → never synced
    assert called == []


def test_recovery_skipped_on_truncated_run(run_main, monkeypatch):
    # on a --max-pages smoke run most cards are "uncrawled" but not dropped —
    # recovery must never treat them as dropped and TCGCSV-blast them
    called = []
    monkeypatch.setattr(snapshot_all, "recover_dropped",
                        lambda db, crawl: called.append(1) or snapshot_all.DroppedFill())
    db = TestingSessionLocal()
    card_catalog.mark_full_sync(db)
    db.close()
    # page 2 drops within a 2-page truncated run: dropped IS non-empty
    assert run_main(["--max-pages", "2"], fail_first={2: 99}) == 0
    assert called == []


def test_no_tcgcsv_flag_also_skips_dropped_recovery(run_main, monkeypatch):
    called = []
    monkeypatch.setattr(snapshot_all, "recover_dropped",
                        lambda db, crawl: called.append(1) or snapshot_all.DroppedFill())
    db = TestingSessionLocal()
    card_catalog.mark_full_sync(db)
    db.close()
    assert run_main(["--no-tcgcsv"], fail_first={3: 99}) == 0
    assert called == []


# ---- Price sanity check against the TCGCSV mirror ---------------------------
# Upstream sometimes serves the WRONG product's price (a [Staff] promo mapped
# onto the regular card) or a junk figure; a >=3x divergence from TCGplayer's
# own mirror, on a name-and-number match, means TCGplayer wins.

def priced_card(card_id: str, price: float, name: str = "Mega Card ex",
                number: str = "188") -> dict:
    card = mega_card(card_id, number=number, name=name)
    card["tcgplayer"] = {"prices": {"holofoil": {"market": price}}}
    return card


def priced_crawl(*cards: dict) -> "snapshot_all.Crawl":
    from app.services.price_history import extract_price
    return snapshot_all.Crawl(
        cards=list(cards),
        prices={c["id"]: extract_price(c) for c in cards})


def test_sanity_check_overrides_wildly_diverging_upstream_price(fake_tcgcsv):
    # upstream says $900 for a card TCGplayer's own mirror prices at $250
    card = priced_card("me9-1", 900.0)
    crawl = priced_crawl(card)
    result = snapshot_all.price_sanity_check(crawl)

    assert result.replaced == {"me9-1": 250.0}
    assert crawl.prices["me9-1"] == 250.0            # the snapshot follows
    assert card["tcgplayer"]["prices"]["holofoil"]["market"] == 250.0
    assert card["tcgplayer"]["priceSource"] == "tcgcsv"


def test_sanity_check_leaves_agreeing_prices_alone(fake_tcgcsv):
    card = priced_card("me9-1", 260.0)               # ~4% off — normal lag
    crawl = priced_crawl(card)
    result = snapshot_all.price_sanity_check(crawl)

    assert result.replaced == {}
    assert crawl.prices["me9-1"] == 260.0
    assert "priceSource" not in card["tcgplayer"]


def test_sanity_check_requires_a_name_match(fake_tcgcsv):
    # same set + number but a different card name: a number-only match is not
    # enough evidence to override a real price (merged groups reuse numbers)
    card = priced_card("me9-9", 900.0, name="Some Other Card")
    crawl = priced_crawl(card)
    result = snapshot_all.price_sanity_check(crawl)

    assert result.replaced == {}
    assert crawl.prices["me9-9"] == 900.0


def test_sanity_corrected_price_lands_in_catalog_and_history(run_main, fake_tcgcsv):
    pages = three_pages()
    pages[2][0] = priced_card("me9-1", 900.0)
    assert run_main(pages=pages) == 0

    db = TestingSessionLocal()
    try:
        stored = card_catalog.get_card(db, "me9-1").data
        assert stored["tcgplayer"]["prices"]["holofoil"]["market"] == 250.0
        assert stored["tcgplayer"]["priceSource"] == "tcgcsv"
        snap = (db.query(CardPriceSnapshot)
                  .filter(CardPriceSnapshot.card_id == "me9-1").one())
        assert snap.price == 250.0
    finally:
        db.close()


# ---- Image check: dead upstream image URLs swapped for TCGplayer scans ------
# The upstream image CDN answers a missing card image with HTTP 404 whose body
# is a card-back PNG, which a browser <img> renders as if it were the artwork.
# image_fill HEAD-checks each URL once (a 200 stamps `verified`, skipped on
# later runs) and re-points 404ing cards at the TCGplayer product scan.

def imaged_card(card_id: str = "me9-1") -> dict:
    """A mega_card (Mega Set / number 188) carrying an images block."""
    card = mega_card(card_id)
    card["images"] = {"small": f"https://img.example/{card_id}/small",
                      "large": f"https://img.example/{card_id}/large"}
    return card


@pytest.fixture
def fake_heads(monkeypatch):
    """_head_image stand-in: statuses keyed by URL (default 200), calls recorded."""
    class FakeHead:
        def __init__(self):
            self.statuses: dict[str, int | None] = {}
            self.calls: list[str] = []

        def __call__(self, url):
            self.calls.append(url)
            return self.statuses.get(url, 200)

    fake = FakeHead()
    monkeypatch.setattr(snapshot_all, "_head_image", fake)
    return fake


def image_fill_on(*cards: dict) -> "snapshot_all.ImageFill":
    db = TestingSessionLocal()
    try:
        return snapshot_all.image_fill(db, snapshot_all.Crawl(cards=list(cards)))
    finally:
        db.close()


def test_live_image_urls_get_the_verified_stamp(fake_heads):
    card = imaged_card()
    fill = image_fill_on(card)

    assert card["images"]["verified"] is True
    assert fill.checked == 1 and fill.substituted == {} and fill.missing == []


def test_dead_image_swapped_for_the_tcgplayer_scan(fake_heads, fake_tcgcsv):
    card = imaged_card()
    fake_heads.statuses["https://img.example/me9-1/small"] = 404
    fill = image_fill_on(card)

    assert card["images"] == {
        "small": "https://cdn.example/product/9_200w.jpg",
        "large": "https://cdn.example/product/9_in_1000x1000.jpg",
        "source": "tcgplayer",
    }
    assert fill.substituted == {"me9-1": "https://cdn.example/product/9_200w.jpg"}


def test_dead_image_without_a_substitute_left_alone(fake_heads, monkeypatch):
    # no TCGCSV match: upstream's URLs stay (the frontend detects the card-back
    # and shows its placeholder) and, unstamped, get re-checked next run
    monkeypatch.setattr(snapshot_all.tcgcsv, "group_id_for_set",
                        lambda name, set_id=None: None)
    card = imaged_card()
    fake_heads.statuses["https://img.example/me9-1/small"] = 404
    fill = image_fill_on(card)

    assert card["images"]["small"] == "https://img.example/me9-1/small"
    assert "verified" not in card["images"]
    assert fill.missing == ["me9-1"]


def test_verified_urls_are_not_rechecked_on_later_runs(fake_heads):
    stamped = imaged_card()
    stamped["images"]["verified"] = True
    db = TestingSessionLocal()
    card_catalog.upsert_cards(db, [stamped])
    db.close()

    fresh = imaged_card()  # same URL, unstamped — as upstream serves it
    fill = image_fill_on(fresh)

    assert fake_heads.calls == [] and fill.checked == 0
    assert fresh["images"]["verified"] is True  # stamp carried through the upsert


def test_substituted_card_heals_back_when_upstream_grows_a_scan(fake_heads):
    # the stored block is tcgplayer-sourced, not verified — so the fresh
    # upstream URL is checked again, passes, and upstream's images win back
    swapped = mega_card()
    swapped["images"] = {"small": "https://cdn.example/product/9_200w.jpg",
                         "large": "https://cdn.example/product/9_in_1000x1000.jpg",
                         "source": "tcgplayer"}
    db = TestingSessionLocal()
    card_catalog.upsert_cards(db, [swapped])
    db.close()

    fresh = imaged_card()
    fill = image_fill_on(fresh)

    assert fake_heads.calls == ["https://img.example/me9-1/small"]
    assert fresh["images"]["small"] == "https://img.example/me9-1/small"
    assert fresh["images"]["verified"] is True
    assert fill.substituted == {}


def test_flaky_check_leaves_the_card_unstamped_for_next_run(fake_heads):
    card = imaged_card()
    fake_heads.statuses["https://img.example/me9-1/small"] = None  # network flake
    fill = image_fill_on(card)

    assert "verified" not in card["images"] and "source" not in card["images"]
    assert fill.errors == 1


def test_swapped_images_land_in_the_catalog(run_main, fake_tcgcsv, monkeypatch):
    # end-to-end: the 404ing card comes out of the run serving the scan
    monkeypatch.setattr(
        snapshot_all, "_head_image",
        lambda url: 404 if url == "https://img.example/me9-1/small" else 200)
    pages = three_pages()
    pages[2][0] = imaged_card()
    assert run_main(pages=pages) == 0

    db = TestingSessionLocal()
    try:
        stored = card_catalog.get_card(db, "me9-1").data
        assert stored["images"]["small"] == "https://cdn.example/product/9_200w.jpg"
        assert stored["images"]["source"] == "tcgplayer"
    finally:
        db.close()


def test_no_tcgcsv_flag_skips_the_image_check(run_main, monkeypatch):
    called = []
    monkeypatch.setattr(
        snapshot_all, "image_fill",
        lambda db, crawl: called.append(1) or snapshot_all.ImageFill())
    assert run_main(["--no-tcgcsv"]) == 0
    assert called == []


# ---- Fossilized catalog prices clear on an authoritative crawl --------------
# A stored prices block whose card now crawls price-less with no TCGCSV match
# has no source backing it (upstream retracted the data); the crawl's upsert
# must clear it so the card degrades to its estimate instead of showing a
# price nobody quotes.

def test_crawl_clears_stored_prices_no_source_backs(run_main):
    db = TestingSessionLocal()
    card_catalog.upsert_cards(
        db, [{**mega_card("c2-0", number="0", name="Test Card"),
              "tcgplayer": {"prices": {"holofoil": {"market": 96.66}}}}])
    db.close()

    pages = three_pages()
    pages[2][0] = mega_card("c2-0", number="0", name="Test Card")  # now price-less
    assert run_main(pages=pages) == 0

    db = TestingSessionLocal()
    try:
        stored = card_catalog.get_card(db, "c2-0").data
        assert not (stored.get("tcgplayer") or {}).get("prices")
    finally:
        db.close()


def test_no_tcgcsv_run_keeps_stored_prices(run_main):
    # without the fill, "no prices in this crawl" isn't proof of anything —
    # the protective keep-rule stays on
    db = TestingSessionLocal()
    card_catalog.upsert_cards(
        db, [{**mega_card("c2-0", number="0", name="Test Card"),
              "tcgplayer": {"prices": {"holofoil": {"market": 96.66}}}}])
    db.close()

    pages = three_pages()
    pages[2][0] = mega_card("c2-0", number="0", name="Test Card")
    assert run_main(["--no-tcgcsv"], pages=pages) == 0

    db = TestingSessionLocal()
    try:
        stored = card_catalog.get_card(db, "c2-0").data
        assert stored["tcgplayer"]["prices"]["holofoil"]["market"] == 96.66
    finally:
        db.close()
