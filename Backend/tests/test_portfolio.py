from app.services import card_catalog
from app.services.price_history import record_snapshots
from conftest import TestingSessionLocal, make_card


def add(client, headers, card_id="base1-4", **body):
    return client.post("/portfolio/add", json={"card_id": card_id, **body}, headers=headers)


def seed_catalog_card(card):
    """Put a priced card into the local catalog, as the daily TCGCSV fill does."""
    db = TestingSessionLocal()
    card_catalog.upsert_cards(db, [card])
    db.close()


def seed_snapshot(card_id, price):
    """Record a price snapshot, as the daily job's eBay-median fill does."""
    db = TestingSessionLocal()
    record_snapshots(db, {card_id: price})
    db.close()


class TestAdd:
    def test_add_with_explicit_price(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4", "Charizard", price=500.0))
        res = add(client, auth_headers, purchase_price=350.0, quantity=2)
        assert res.status_code == 200
        assert res.json()["message"] == "Card added"

        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["card_name"] == "Charizard"
        assert row["purchase_price"] == 350.0
        assert row["quantity"] == 2

    def test_add_without_price_uses_market_price(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4", price=500.0))
        add(client, auth_headers)
        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["purchase_price"] == 500.0
        assert row["quantity"] == 1

    def test_add_priceless_card_without_price_rejected(self, client, auth_headers, upstream):
        upstream.add(make_card("me1-1", price=None))
        res = add(client, auth_headers, card_id="me1-1")
        assert res.status_code == 400
        assert "purchase price" in res.json()["detail"]

    def test_add_priceless_card_with_explicit_price_ok(self, client, auth_headers, upstream):
        upstream.add(make_card("me1-1", price=None))
        res = add(client, auth_headers, card_id="me1-1", purchase_price=5.0)
        assert res.status_code == 200

    def test_add_unknown_card(self, client, auth_headers):
        res = add(client, auth_headers, card_id="nope-1")
        assert res.status_code == 404

    def test_negative_price_rejected(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4"))
        assert add(client, auth_headers, purchase_price=-1).status_code == 422

    def test_zero_quantity_rejected(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4"))
        assert add(client, auth_headers, quantity=0).status_code == 422

    def test_second_purchase_is_a_separate_lot(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4", price=500.0))
        add(client, auth_headers, purchase_price=100.0)
        res = add(client, auth_headers, purchase_price=200.0, quantity=2)
        assert "you now have 3 total" in res.json()["message"]

        rows = client.get("/portfolio", headers=auth_headers).json()
        # one row per lot — prices are never merged or averaged
        assert sorted(r["purchase_price"] for r in rows) == [100.0, 200.0]


class TestGetPortfolio:
    def test_live_price_and_gain_loss(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4", price=500.0))
        add(client, auth_headers, purchase_price=400.0, quantity=2)

        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["current_price"] == 500.0
        assert row["gain_loss"] == 200.0  # (500 - 400) * 2
        assert row["gain_loss_pct"] == 25.0

    def test_image_url_comes_from_upstream(self, client, auth_headers, upstream):
        upstream.add(make_card("me2pt5-277", image="https://images.scrydex.com/pokemon/me2pt5-277/small"))
        add(client, auth_headers, card_id="me2pt5-277")
        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["image_url"] == "https://images.scrydex.com/pokemon/me2pt5-277/small"

    def test_priceless_card_has_null_price_fields(self, client, auth_headers, upstream):
        upstream.add(make_card("me1-1", price=None))
        add(client, auth_headers, card_id="me1-1", purchase_price=5.0)
        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["current_price"] is None
        assert row["gain_loss"] is None

    def test_users_only_see_their_own_cards(self, client, auth_headers, second_auth_headers, upstream):
        upstream.add(make_card("base1-4"))
        add(client, auth_headers)
        assert client.get("/portfolio", headers=second_auth_headers).json() == []


class TestUpdateAndDelete:
    def test_update_lot(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4"))
        lot_id = add(client, auth_headers, purchase_price=10.0).json()["id"]

        res = client.patch(f"/portfolio/{lot_id}", json={"purchase_price": 12.5, "quantity": 3},
                           headers=auth_headers)
        assert res.status_code == 200
        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["purchase_price"] == 12.5
        assert row["quantity"] == 3

    def test_update_validation(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4"))
        lot_id = add(client, auth_headers).json()["id"]
        assert client.patch(f"/portfolio/{lot_id}", json={"quantity": 0},
                            headers=auth_headers).status_code == 422
        assert client.patch(f"/portfolio/{lot_id}", json={"purchase_price": -5},
                            headers=auth_headers).status_code == 422

    def test_cannot_touch_another_users_lot(self, client, auth_headers, second_auth_headers, upstream):
        upstream.add(make_card("base1-4"))
        lot_id = add(client, auth_headers).json()["id"]
        assert client.patch(f"/portfolio/{lot_id}", json={"quantity": 5},
                            headers=second_auth_headers).status_code == 404
        assert client.delete(f"/portfolio/{lot_id}", headers=second_auth_headers).status_code == 404

    def test_delete_lot(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4"))
        lot_id = add(client, auth_headers).json()["id"]
        assert client.delete(f"/portfolio/{lot_id}", headers=auth_headers).status_code == 200
        assert client.get("/portfolio", headers=auth_headers).json() == []
        assert client.delete(f"/portfolio/{lot_id}", headers=auth_headers).status_code == 404


class TestPriceFallbackSources:
    """The portfolio must track a card's value from every price source — the
    live pokemontcg.io TCGplayer figure, then TCGCSV, then eBay — so newest-set
    cards (e.g. Ascended Heroes) that upstream returns unpriced still show a
    price once the daily job has seeded one."""

    def test_catalog_tcgcsv_price_when_upstream_unpriced(self, client, auth_headers, upstream):
        # pokemontcg.io returns this new-set card without a price...
        upstream.add(make_card("me5-1", price=None))
        # ...but the daily job seeded a real TCGplayer price (via TCGCSV) into
        # the local catalog
        seed_catalog_card(make_card("me5-1", price=25.0))
        add(client, auth_headers, card_id="me5-1", purchase_price=10.0)

        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["current_price"] == 25.0
        assert row["gain_loss"] == 15.0  # (25 - 10) * 1

    def test_ebay_snapshot_price_when_upstream_and_catalog_unpriced(self, client, auth_headers, upstream):
        upstream.add(make_card("me5-2", price=None))
        # No TCGCSV catalog price either — only the daily job's recorded eBay median
        seed_snapshot("me5-2", 30.0)
        add(client, auth_headers, card_id="me5-2", purchase_price=12.0)

        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["current_price"] == 30.0

    def test_live_upstream_price_wins_over_catalog(self, client, auth_headers, upstream):
        # When upstream has a price it stays the source of truth (freshest)
        upstream.add(make_card("base1-4", price=500.0))
        seed_catalog_card(make_card("base1-4", price=999.0))
        add(client, auth_headers, purchase_price=400.0)

        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["current_price"] == 500.0

    def test_add_without_price_uses_catalog_fallback(self, client, auth_headers, upstream):
        upstream.add(make_card("me5-3", price=None))
        seed_catalog_card(make_card("me5-3", price=7.5))
        assert add(client, auth_headers, card_id="me5-3").status_code == 200

        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["purchase_price"] == 7.5
        assert row["current_price"] == 7.5

    def test_add_without_price_uses_snapshot_fallback(self, client, auth_headers, upstream):
        upstream.add(make_card("me5-4", price=None))
        seed_snapshot("me5-4", 18.0)
        assert add(client, auth_headers, card_id="me5-4").status_code == 200

        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["purchase_price"] == 18.0


class TestHistory:
    def test_empty_without_cards(self, client, auth_headers):
        assert client.get("/portfolio/history", headers=auth_headers).json() == []

    def test_snapshot_recorded_on_portfolio_load(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4", price=500.0))
        add(client, auth_headers, purchase_price=400.0, quantity=2)
        client.get("/portfolio", headers=auth_headers)  # records today's snapshot

        history = client.get("/portfolio/history", headers=auth_headers).json()
        assert len(history) == 1
        assert history[0]["total_value"] == 1000.0  # 500 * qty 2
