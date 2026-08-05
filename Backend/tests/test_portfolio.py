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

    def test_explicit_purchase_date_is_preserved(self, client, auth_headers, upstream):
        # CSV import (backup/restore) sends the lot's original date
        upstream.add(make_card("base1-4", price=500.0))
        add(client, auth_headers, purchase_price=350.0, purchase_date="2021-03-04T00:00:00")
        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["purchase_date"].startswith("2021-03-04")

    def test_omitted_purchase_date_defaults_to_now(self, client, auth_headers, upstream):
        # No date -> the column's default=utcnow fires (not NULL)
        upstream.add(make_card("base1-4", price=500.0))
        add(client, auth_headers, purchase_price=1.0)
        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["purchase_date"] is not None


class TestAddBatch:
    """Batch add for the scanner's batch mode. Scanned ids are catalog rows, so
    names/prices resolve from the catalog without a per-card upstream call."""

    def batch(self, client, headers, items):
        return client.post("/portfolio/add-batch", json={"items": items}, headers=headers)

    def test_adds_multiple_lots_explicit_and_auto_price(self, client, auth_headers):
        seed_catalog_card(make_card("base1-4", "Charizard", price=500.0))
        seed_catalog_card(make_card("base1-2", "Blastoise", price=300.0))
        res = self.batch(client, auth_headers, [
            {"card_id": "base1-4", "purchase_price": 350.0, "quantity": 2},
            {"card_id": "base1-2"},  # no price -> auto-fill from the catalog
        ])
        assert res.status_code == 200
        body = res.json()
        assert body["added"] == 2
        assert body["failed"] == []

        rows = client.get("/portfolio", headers=auth_headers).json()
        by_name = {r["card_name"]: r for r in rows}
        assert by_name["Charizard"]["purchase_price"] == 350.0
        assert by_name["Charizard"]["quantity"] == 2
        assert by_name["Blastoise"]["purchase_price"] == 300.0  # auto from catalog price
        assert by_name["Blastoise"]["quantity"] == 1

    def test_reports_failures_but_still_adds_the_rest(self, client, auth_headers):
        seed_catalog_card(make_card("base1-4", "Charizard", price=500.0))
        res = self.batch(client, auth_headers, [
            {"card_id": "base1-4", "purchase_price": 10.0},
            {"card_id": "ghost-999"},  # not in the catalog
        ])
        assert res.status_code == 200
        body = res.json()
        assert body["added"] == 1
        assert [f["card_id"] for f in body["failed"]] == ["ghost-999"]

        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["card_name"] == "Charizard"

    def test_auto_price_with_no_source_fails_that_item(self, client, auth_headers):
        # A catalog card with no price and no snapshot can't auto-price
        seed_catalog_card(make_card("me1-9", "Priceless", price=None))
        body = self.batch(client, auth_headers, [{"card_id": "me1-9"}]).json()
        assert body["added"] == 0
        assert body["failed"][0]["card_id"] == "me1-9"
        assert client.get("/portfolio", headers=auth_headers).json() == []

    def test_empty_batch_rejected(self, client, auth_headers):
        assert self.batch(client, auth_headers, []).status_code == 422

    def test_users_only_add_to_their_own_portfolio(self, client, auth_headers, second_auth_headers):
        seed_catalog_card(make_card("base1-4", "Charizard", price=500.0))
        self.batch(client, auth_headers, [{"card_id": "base1-4", "purchase_price": 10.0}])
        assert client.get("/portfolio", headers=second_auth_headers).json() == []

    def test_preserves_purchase_date_and_defaults_when_omitted(self, client, auth_headers):
        # CSV import round-trip: a dated lot keeps its date; an undated one defaults to now
        seed_catalog_card(make_card("base1-4", "Charizard", price=500.0))
        self.batch(client, auth_headers, [
            {"card_id": "base1-4", "purchase_price": 10.0, "purchase_date": "2019-11-08T00:00:00"},
            {"card_id": "base1-4", "purchase_price": 20.0},
        ])
        rows = client.get("/portfolio", headers=auth_headers).json()
        by_price = {r["purchase_price"]: r for r in rows}
        assert by_price[10.0]["purchase_date"].startswith("2019-11-08")
        assert by_price[20.0]["purchase_date"] is not None


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

    def test_variety_card_is_holdable_and_priced_from_catalog(self, client, auth_headers, upstream):
        # A stamp/mark variety lives only in the catalog (the daily job forks it);
        # pokemontcg.io has no such id, so it must resolve without any upstream
        # call — both the add lookup and the /portfolio price come from the catalog
        seed_catalog_card(make_card("swshp-SWSH006~v208260", price=900.0))
        assert add(client, auth_headers,
                   card_id="swshp-SWSH006~v208260").status_code == 200

        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["current_price"] == 900.0
        assert row["purchase_price"] == 900.0  # auto-filled from the catalog price


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


import app.routers.cards as cards_module  # for monkeypatching sets_by_id

# Stubbed sets list (what cards.sets_by_id() serves): master `total` is the
# denominator; Surging Sparks has secret rares so total (207) != printedTotal (191).
_SETS = {
    "base1": {"id": "base1", "name": "Base", "series": "Base",
              "releaseDate": "1999/01/09", "total": 102, "printedTotal": 102,
              "images": {"logo": "logo-url", "symbol": "symbol-url"}},
    "sv8": {"id": "sv8", "name": "Surging Sparks", "series": "Scarlet & Violet",
            "releaseDate": "2024/11/08", "total": 207, "printedTotal": 191,
            "images": {}},
}


class TestSetCompletion:
    def test_requires_auth(self, client):
        assert client.get("/portfolio/set-completion").status_code == 401

    def test_empty_without_cards(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(cards_module, "sets_by_id", lambda: _SETS)
        assert client.get("/portfolio/set-completion", headers=auth_headers).json() == []

    def test_counts_distinct_cards_per_set(self, client, auth_headers, upstream, monkeypatch):
        monkeypatch.setattr(cards_module, "sets_by_id", lambda: _SETS)
        for cid in ("base1-4", "base1-2", "sv8-1"):
            upstream.add(make_card(cid, price=10.0))
        add(client, auth_headers, card_id="base1-4")
        add(client, auth_headers, card_id="base1-4")  # a 2nd lot of the same card
        add(client, auth_headers, card_id="base1-2")
        add(client, auth_headers, card_id="sv8-1")

        res = client.get("/portfolio/set-completion", headers=auth_headers)
        assert res.status_code == 200
        by_set = {s["set_id"]: s for s in res.json()}
        # base1: 2 distinct cards owned (the repeat lot doesn't double-count)
        assert by_set["base1"]["owned"] == 2
        assert by_set["base1"]["total"] == 102          # master total, secret rares in
        assert by_set["base1"]["printed_total"] == 102
        assert by_set["base1"]["set_name"] == "Base"
        assert by_set["base1"]["logo"] == "logo-url"
        # sv8: 1 owned against the 207 master total (191 printed)
        assert by_set["sv8"]["owned"] == 1
        assert by_set["sv8"]["total"] == 207
        assert by_set["sv8"]["printed_total"] == 191

    def test_sorted_nearest_to_complete_first(self, client, auth_headers, upstream, monkeypatch):
        monkeypatch.setattr(cards_module, "sets_by_id", lambda: _SETS)
        for cid in ("base1-4", "base1-2", "sv8-1"):
            upstream.add(make_card(cid, price=10.0))
        add(client, auth_headers, card_id="base1-4")   # base1: 2/102 ~ 2%
        add(client, auth_headers, card_id="base1-2")
        add(client, auth_headers, card_id="sv8-1")      # sv8:  1/207 ~ 0.5%
        result = client.get("/portfolio/set-completion", headers=auth_headers).json()
        assert [s["set_id"] for s in result] == ["base1", "sv8"]

    def test_excludes_varieties(self, client, auth_headers, upstream, monkeypatch):
        monkeypatch.setattr(cards_module, "sets_by_id", lambda: _SETS)
        upstream.add(make_card("base1-4", price=10.0))
        add(client, auth_headers, card_id="base1-4")
        # a stamp/mark variety lives only in the catalog — never a set's printed card
        seed_catalog_card(make_card("base1-4~v999", "Charizard [Staff]", price=20.0))
        assert add(client, auth_headers, card_id="base1-4~v999").status_code == 200

        [s] = client.get("/portfolio/set-completion", headers=auth_headers).json()
        assert s["set_id"] == "base1"
        assert s["owned"] == 1  # the variety is not counted toward completion

    def test_scopes_to_portfolio(self, client, auth_headers, upstream, monkeypatch):
        monkeypatch.setattr(cards_module, "sets_by_id", lambda: _SETS)
        upstream.add(make_card("base1-4", price=10.0))
        upstream.add(make_card("sv8-1", price=10.0))
        add(client, auth_headers, card_id="base1-4")   # default portfolio
        binder = client.post("/portfolios", json={"name": "Binder"}, headers=auth_headers).json()
        add(client, auth_headers, card_id="sv8-1", portfolio_id=binder["id"])

        # account-wide (no portfolio_id) sees both sets
        allwide = client.get("/portfolio/set-completion", headers=auth_headers).json()
        assert {s["set_id"] for s in allwide} == {"base1", "sv8"}
        # scoped to Binder sees only its set
        scoped = client.get(
            f"/portfolio/set-completion?portfolio_id={binder['id']}", headers=auth_headers
        ).json()
        assert {s["set_id"] for s in scoped} == {"sv8"}

    def test_unknown_set_falls_back_to_owned_total(self, client, auth_headers, upstream, monkeypatch):
        # A set not in the sets list (and no catalog rows) → total falls back to
        # the owned count, and the name to the set id.
        monkeypatch.setattr(cards_module, "sets_by_id", lambda: {})
        upstream.add(make_card("xy1-1", price=10.0))
        add(client, auth_headers, card_id="xy1-1")
        [s] = client.get("/portfolio/set-completion", headers=auth_headers).json()
        assert s["set_id"] == "xy1"
        assert s["owned"] == 1
        assert s["total"] == 1
        assert s["set_name"] == "xy1"
