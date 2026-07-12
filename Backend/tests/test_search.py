"""Card search endpoints — pagination envelope, per-page caching, smart-search fallback.

card_api talks to the upstream API through its own module-level `session`
(separate from portfolio._session); these tests swap it for a fake that
serves paged card data, so they run offline like the rest of the suite.
"""
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
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url: str, params: dict | None = None):
        self.calls.append((url, params))
        if url.endswith("/sets"):
            return FakeResponse(200, {"data": self.sets})
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
    yield fake
    card_api._cache.clear()


def test_cards_returns_page_envelope(client, cards_upstream):
    cards_upstream.card_lists["set.id:base1"] = make_cards(3)
    res = client.get("/cards", params={"set_id": "base1"})
    assert res.status_code == 200
    body = res.json()
    assert len(body["data"]) == 3
    assert body["page"] == 1
    assert body["pageSize"] == 250
    assert body["totalCount"] == 3


def test_cards_second_page(client, cards_upstream):
    cards_upstream.card_lists['name:"pikachu"'] = make_cards(600)
    res = client.get("/cards", params={"name": "pikachu", "page": 2})
    body = res.json()
    assert body["page"] == 2
    assert body["totalCount"] == 600
    assert len(body["data"]) == 250
    assert body["data"][0]["id"] == "test-250"


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
