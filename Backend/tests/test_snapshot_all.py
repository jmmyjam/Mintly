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


def test_page_failing_both_passes_marks_incomplete(crawl):
    result = crawl({3: 99})  # page 3 never succeeds
    assert not result.complete
    assert result.dropped == [3]
    assert len(result.prices) == 4  # the other pages were still collected
    assert "c3-0" not in result.prices


# ---- Catalog upsert + sync marker -------------------------------------------
# The crawl mirrors every card into card_catalog; only a complete, un-truncated
# run may stamp the sync marker that lets list endpoints trust the catalog.

@pytest.fixture
def run_main(monkeypatch):
    monkeypatch.setattr(snapshot_all, "_PAGE_SIZE", 2)
    monkeypatch.setattr(snapshot_all.time, "sleep", lambda s: None)
    monkeypatch.setattr(snapshot_all, "SessionLocal", TestingSessionLocal)

    def run(extra_args: list[str] = [], fail_first: dict[int, int] = {}):
        fake = FlakyUpstream(three_pages(), fail_first)
        monkeypatch.setattr(snapshot_all, "session", fake)
        monkeypatch.setattr(sys, "argv", ["snapshot_all.py", "--max-ebay", "0",
                                          "--no-compact", *extra_args])
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

def test_crawl_collects_unpriced_card_metadata(crawl, monkeypatch):
    pages = three_pages()
    pages[2][0] = {
        "id": "me9-1", "name": "Mega Card ex", "number": "188",
        "set": {"name": "Mega Set", "releaseDate": "2026/05/30"},
    }
    fake = FlakyUpstream(pages, {})
    monkeypatch.setattr(snapshot_all, "session", fake)
    result = snapshot_all.fetch_all_prices()

    assert "me9-1" not in result.prices
    assert result.unpriced == [{
        "id": "me9-1", "name": "Mega Card ex", "number": "188",
        "set_name": "Mega Set", "release": "2026/05/30",
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
