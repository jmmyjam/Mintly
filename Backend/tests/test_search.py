"""Card search endpoints — pagination envelope, per-page caching, smart-search fallback.

card_api talks to the upstream API through its own module-level `session`
(separate from portfolio._session); these tests swap it for a fake that
serves paged card data, so they run offline like the rest of the suite.
"""
import time

import pytest

import card_api


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakePagedUpstream:
    """Serves /cards from per-query card lists, slicing by page/pageSize."""

    def __init__(self):
        self.card_lists: dict[str, list] = {}  # q -> full result list
        self.sets: list = []
        self.sets_status = 200          # set to e.g. 404 to simulate upstream flakes
        self.sets_exc: Exception | None = None  # raised on /sets to simulate timeouts
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url: str, params: dict | None = None, timeout=None):
        self.calls.append((url, params))
        if url.endswith("/sets"):
            if self.sets_exc:
                raise self.sets_exc
            return FakeResponse(self.sets_status, {"data": self.sets})
        if url.endswith("/cards") and params:
            full = self.card_lists.get(params["q"], [])
            page, size = params["page"], params["pageSize"]
            chunk = full[(page - 1) * size : page * size]
            return FakeResponse(200, {
                "data": chunk,
                "page": page,
                "pageSize": size,
                "count": len(chunk),
                "totalCount": len(full),
            })
        return FakeResponse(404, {"error": "not found"})

    def card_calls(self) -> list[dict]:
        return [p for (url, p) in self.calls if url.endswith("/cards")]


def make_cards(n: int, name: str = "Pikachu") -> list[dict]:
    return [{"id": f"test-{i}", "name": name} for i in range(n)]


@pytest.fixture
def cards_upstream(monkeypatch):
    fake = FakePagedUpstream()
    monkeypatch.setattr(card_api, "session", fake)
    card_api._cache.clear()
    card_api._refreshing.clear()
    yield fake
    card_api._cache.clear()
    card_api._refreshing.clear()


def test_cards_returns_page_envelope(client, cards_upstream):
    cards_upstream.card_lists["set.id:base1"] = make_cards(3)
    res = client.get("/cards", params={"set_id": "base1"})
    assert res.status_code == 200
    body = res.json()
    assert len(body["data"]) == 3
    assert body["page"] == 1
    assert body["pageSize"] == 50
    assert body["totalCount"] == 3


def test_cards_second_page(client, cards_upstream):
    cards_upstream.card_lists['name:"pikachu"'] = make_cards(600)
    res = client.get("/cards", params={"name": "pikachu", "page": 2})
    body = res.json()
    assert body["page"] == 2
    assert body["totalCount"] == 600
    assert len(body["data"]) == 50
    assert body["data"][0]["id"] == "test-50"


def test_cards_page_must_be_positive(client, cards_upstream):
    res = client.get("/cards", params={"name": "pikachu", "page": 0})
    assert res.status_code == 422


def test_pages_cached_separately(client, cards_upstream):
    cards_upstream.card_lists['name:"pikachu"'] = make_cards(600)
    client.get("/cards", params={"name": "pikachu", "page": 1})
    client.get("/cards", params={"name": "pikachu", "page": 1})  # cache hit
    client.get("/cards", params={"name": "pikachu", "page": 2})  # new page → upstream
    pages_fetched = [p["page"] for p in cards_upstream.card_calls()]
    assert pages_fetched == [1, 2]


def test_search_passes_page_through(client, cards_upstream):
    cards_upstream.card_lists['name:"pikachu"'] = make_cards(300)
    res = client.get("/search", params={"q": "pikachu", "page": 2})
    body = res.json()
    assert body["page"] == 2
    assert body["totalCount"] == 300
    assert len(body["data"]) == 50


def test_search_fallback_uses_total_count(client, cards_upstream):
    # "sleepy pikachu" matches nothing → fallback drops to "pikachu"
    cards_upstream.card_lists['name:"pikachu"'] = make_cards(10)
    res = client.get("/search", params={"q": "sleepy pikachu"})
    body = res.json()
    assert body["totalCount"] == 10
    assert len(body["data"]) == 10


def test_search_empty_page_does_not_trigger_fallback(client, cards_upstream):
    # Page 2 of a 10-card query is empty, but the query itself matched —
    # the word-dropping fallback must not kick in
    cards_upstream.card_lists['name:"sleepy pikachu"'] = make_cards(10, "Sleepy Pikachu")
    res = client.get("/search", params={"q": "sleepy pikachu", "page": 2})
    body = res.json()
    assert body["totalCount"] == 10
    assert body["data"] == []
    assert len(cards_upstream.card_calls()) == 1


def _age_cache_entry(key: str, by: float):
    ts, data = card_api._cache[key]
    card_api._cache[key] = (ts - by, data)


def _wait_for_refresh(key: str, want_len: int, timeout: float = 2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(card_api._cache[key][1]["data"]) == want_len:
            return
        time.sleep(0.01)
    raise AssertionError("background refresh never updated the cache")


def test_stale_cache_served_immediately_then_refreshed(client, cards_upstream):
    cards_upstream.card_lists['name:"pikachu"'] = make_cards(1)
    client.get("/cards", params={"name": "pikachu"})  # primes the cache
    key = 'name:"pikachu"|page:1'
    _age_cache_entry(key, card_api._CACHE_TTL + 1)
    cards_upstream.card_lists['name:"pikachu"'] = make_cards(2)  # upstream moved on

    body = client.get("/cards", params={"name": "pikachu"}).json()
    assert len(body["data"]) == 1  # stale data served without waiting on upstream

    _wait_for_refresh(key, 2)
    body = client.get("/cards", params={"name": "pikachu"}).json()
    assert len(body["data"]) == 2  # next request sees the refreshed entry


def test_too_stale_cache_is_refetched_synchronously(client, cards_upstream):
    cards_upstream.card_lists['name:"pikachu"'] = make_cards(1)
    client.get("/cards", params={"name": "pikachu"})
    _age_cache_entry('name:"pikachu"|page:1', card_api._STALE_TTL + 1)
    cards_upstream.card_lists['name:"pikachu"'] = make_cards(2)

    body = client.get("/cards", params={"name": "pikachu"}).json()
    assert len(body["data"]) == 2  # dead entry: fetched fresh, not served stale


def _expire_sets_cache():
    ts, data = card_api._cache["__sets__"]
    card_api._cache["__sets__"] = (ts - card_api._CACHE_TTL - 1, data)


def test_sets_stale_cache_served_when_upstream_errors(client, cards_upstream):
    cards_upstream.sets = [{"id": "base1", "name": "Base"}]
    assert client.get("/sets").status_code == 200  # primes the cache
    _expire_sets_cache()
    cards_upstream.sets_status = 404  # the observed transient upstream flake
    res = client.get("/sets")
    assert res.status_code == 200
    assert res.json() == [{"id": "base1", "name": "Base"}]


def test_sets_stale_cache_served_when_upstream_times_out(client, cards_upstream):
    import requests

    cards_upstream.sets = [{"id": "base1", "name": "Base"}]
    client.get("/sets")
    _expire_sets_cache()
    cards_upstream.sets_exc = requests.ConnectTimeout("upstream hang")
    res = client.get("/sets")
    assert res.status_code == 200
    assert res.json() == [{"id": "base1", "name": "Base"}]


def test_sets_cold_cache_upstream_error_still_fails(client, cards_upstream):
    cards_upstream.sets_status = 404
    res = client.get("/sets")
    assert res.status_code == 404
    assert res.json()["detail"] == "Failed to fetch sets"
