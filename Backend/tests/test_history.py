"""Price history + daily change: snapshots are recorded for any browsed card,
`priceChange` is attached vs the prior snapshot, /cards/{id}/history serves the
per-card series, and /portfolio carries each row's daily change.

cards talks upstream through its own module-level `session`; these tests swap
it for a fake serving priced cards, and insert prior-day snapshots straight into
the shared in-memory DB.
"""
import time
from datetime import timedelta

import pytest

from app.routers import cards
from conftest import TestingSessionLocal, make_card
from app.models import CardPriceSnapshot, utcnow
from app.services.price_history import extract_price


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeCardsUpstream:
    """Serves /cards (param queries return all registered cards, paged) and
    /cards/{id} (single), plus /sets — enough for the card-proxy endpoints."""

    def __init__(self):
        self.by_id: dict[str, dict] = {}
        self.sets: list = []

    def add(self, card: dict):
        self.by_id[card["id"]] = card

    def get(self, url, params=None, timeout=None):
        if url.endswith("/sets"):
            return FakeResponse(200, {"data": self.sets})
        if url.endswith("/cards") and params:
            cards = list(self.by_id.values())
            page, size = params.get("page", 1), params.get("pageSize", 250)
            chunk = cards[(page - 1) * size: page * size]
            return FakeResponse(200, {
                "data": chunk, "page": page, "pageSize": size,
                "totalCount": len(cards),
            })
        card_id = url.rsplit("/", 1)[1]
        if card_id in self.by_id:
            return FakeResponse(200, {"data": self.by_id[card_id]})
        return FakeResponse(404, {"error": "not found"})


@pytest.fixture
def cards_upstream(monkeypatch):
    fake = FakeCardsUpstream()
    monkeypatch.setattr(cards, "session", fake)
    cards._cache.clear()
    cards._refreshing.clear()
    yield fake
    cards._cache.clear()
    cards._refreshing.clear()


def seed_prior_snapshot(card_id: str, price: float, days_ago: int = 1):
    db = TestingSessionLocal()
    db.add(CardPriceSnapshot(
        card_id=card_id, price=price,
        snapshot_date=utcnow() - timedelta(days=days_ago),
    ))
    db.commit()
    db.close()


def count_snapshots(card_id: str) -> int:
    db = TestingSessionLocal()
    n = db.query(CardPriceSnapshot).filter(CardPriceSnapshot.card_id == card_id).count()
    db.close()
    return n


class TestSnapshotRecording:
    def test_browsing_a_priced_card_records_a_snapshot(self, client, cards_upstream):
        cards_upstream.add(make_card("sv1-1", price=12.0))
        client.get("/cards", params={"set_id": "sv1"})
        assert count_snapshots("sv1-1") == 1

    def test_priceless_card_records_nothing(self, client, cards_upstream):
        cards_upstream.add(make_card("me4-1", price=None))
        client.get("/cards", params={"set_id": "me4"})
        assert count_snapshots("me4-1") == 0

    def test_one_snapshot_per_day(self, client, cards_upstream):
        cards_upstream.add(make_card("sv1-1", price=12.0))
        client.get("/cards", params={"set_id": "sv1"})
        client.get("/cards", params={"set_id": "sv1"})  # same UTC day
        assert count_snapshots("sv1-1") == 1

    def test_single_card_lookup_records_snapshot(self, client, cards_upstream):
        cards_upstream.add(make_card("sv1-2", price=8.0))
        client.get("/cards/sv1-2")
        assert count_snapshots("sv1-2") == 1


class TestPriceChangeAnnotation:
    def test_change_attached_vs_prior_snapshot(self, client, cards_upstream):
        cards_upstream.add(make_card("sv1-3", price=110.0))
        seed_prior_snapshot("sv1-3", 100.0)
        card = client.get("/cards/sv1-3").json()
        assert card["priceChange"]["amount"] == 10.0
        assert card["priceChange"]["percent"] == 10.0

    def test_no_change_without_prior_snapshot(self, client, cards_upstream):
        cards_upstream.add(make_card("sv1-4", price=110.0))
        card = client.get("/cards/sv1-4").json()
        assert "priceChange" not in card

    def test_search_results_carry_change(self, client, cards_upstream):
        cards_upstream.add(make_card("sv1-5", "Pikachu", price=50.0))
        seed_prior_snapshot("sv1-5", 40.0)
        body = client.get("/search", params={"q": "Pikachu"}).json()
        assert body["data"][0]["priceChange"]["amount"] == 10.0


class TestCardHistory:
    def test_history_returns_daily_points(self, client, cards_upstream):
        cards_upstream.add(make_card("sv1-6", price=30.0))
        seed_prior_snapshot("sv1-6", 20.0, days_ago=2)
        seed_prior_snapshot("sv1-6", 25.0, days_ago=1)
        client.get("/cards/sv1-6")  # today's point
        history = client.get("/cards/sv1-6/history").json()
        prices = [p["price"] for p in history]
        assert prices == [20.0, 25.0, 30.0]  # oldest first

    def test_history_window_excludes_old_points(self, client, cards_upstream):
        seed_prior_snapshot("sv1-7", 5.0, days_ago=400)
        seed_prior_snapshot("sv1-7", 6.0, days_ago=10)
        history = client.get("/cards/sv1-7/history", params={"days": 30}).json()
        assert [p["price"] for p in history] == [6.0]

    def test_history_empty_for_unknown_card(self, client, cards_upstream):
        assert client.get("/cards/nope-1/history").json() == []


class TestPortfolioDailyChange:
    def test_portfolio_row_has_daily_change(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4", price=120.0))
        client.post("/portfolio/add",
                    json={"card_id": "base1-4", "purchase_price": 100.0},
                    headers=auth_headers)
        seed_prior_snapshot("base1-4", 100.0)
        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["price_change"]["amount"] == 20.0
        assert row["price_change"]["percent"] == 20.0

    def test_no_change_without_prior_snapshot(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4", price=120.0))
        client.post("/portfolio/add",
                    json={"card_id": "base1-4", "purchase_price": 100.0},
                    headers=auth_headers)
        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["price_change"] is None


class TestStaleSingleCardCache:
    def test_stale_card_served_then_refreshed(self, client, cards_upstream):
        def market(card):
            return card["tcgplayer"]["prices"]["holofoil"]["market"]

        cards_upstream.add(make_card("sv1-9", price=10.0))
        client.get("/cards/sv1-9")  # primes the cache
        key = "__card__sv1-9"
        ts, data = cards._cache[key]
        cards._cache[key] = (ts - cards._CACHE_TTL - 1, data)
        cards_upstream.add(make_card("sv1-9", price=20.0))  # upstream moved on

        assert market(client.get("/cards/sv1-9").json()) == 10.0  # stale, instant

        deadline = time.time() + 2
        while time.time() < deadline and market(cards._cache[key][1]) != 20.0:
            time.sleep(0.01)
        assert market(client.get("/cards/sv1-9").json()) == 20.0  # refresh landed


class TestExtractPrice:
    def test_market_preferred_over_mid(self):
        card = {"tcgplayer": {"prices": {"holofoil": {"market": 12.5, "mid": 15.0}}}}
        assert extract_price(card) == 12.5

    def test_falls_back_to_mid_without_market(self):
        card = {"tcgplayer": {"prices": {"holofoil": {"mid": 15.0}}}}
        assert extract_price(card) == 15.0

    def test_variant_order_beats_price_field(self):
        # holofoil wins over normal even when only holofoil's mid is available
        card = {"tcgplayer": {"prices": {
            "normal": {"market": 3.0, "mid": 4.0},
            "holofoil": {"mid": 15.0},
        }}}
        assert extract_price(card) == 15.0

    def test_no_prices_returns_none(self):
        assert extract_price({"tcgplayer": {"prices": {}}}) is None
        assert extract_price({}) is None
