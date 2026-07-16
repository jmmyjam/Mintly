"""snapshot_all's crawl: pages that fail their inline retries are remembered and
re-tried in an end-of-run second pass; only a page failing both passes marks the
run incomplete (and never aborts the crawl)."""
import os
import sys

import pytest

# the script lives outside the app package, so put scripts/ on the path
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import snapshot_all
from conftest import make_card


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
