"""Multiple named portfolios: CRUD, ownership scoping, and add targeting."""
from conftest import make_card


def names(portfolios):
    return [p["name"] for p in portfolios]


class TestListAndDefault:
    def test_list_creates_default_on_first_call(self, client, auth_headers):
        body = client.get("/portfolios", headers=auth_headers).json()
        assert len(body) == 1
        assert body[0]["name"] == "My Portfolio"
        assert body[0]["is_default"] is True
        assert body[0]["card_count"] == 0

    def test_adding_a_card_auto_creates_the_default(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4", price=500.0))
        client.post("/portfolio/add", headers=auth_headers,
                    json={"card_id": "base1-4", "purchase_price": 10.0})
        body = client.get("/portfolios", headers=auth_headers).json()
        assert len(body) == 1
        assert body[0]["is_default"] is True
        assert body[0]["card_count"] == 1

    def test_default_listed_first(self, client, auth_headers):
        client.post("/portfolios", headers=auth_headers, json={"name": "Trade Binder"})
        body = client.get("/portfolios", headers=auth_headers).json()
        assert names(body) == ["My Portfolio", "Trade Binder"]


class TestCreateRenameDelete:
    def test_create_returns_the_portfolio(self, client, auth_headers):
        res = client.post("/portfolios", headers=auth_headers, json={"name": "Keepers"})
        assert res.status_code == 200
        body = res.json()
        assert body["name"] == "Keepers"
        assert body["is_default"] is False
        assert body["card_count"] == 0

    def test_name_is_trimmed(self, client, auth_headers):
        body = client.post("/portfolios", headers=auth_headers, json={"name": "  Keepers  "}).json()
        assert body["name"] == "Keepers"

    def test_blank_name_rejected(self, client, auth_headers):
        assert client.post("/portfolios", headers=auth_headers, json={"name": "   "}).status_code == 422
        assert client.post("/portfolios", headers=auth_headers, json={"name": ""}).status_code == 422

    def test_too_long_name_rejected(self, client, auth_headers):
        assert client.post("/portfolios", headers=auth_headers, json={"name": "x" * 61}).status_code == 422

    def test_duplicate_name_rejected_case_insensitively(self, client, auth_headers):
        client.post("/portfolios", headers=auth_headers, json={"name": "Keepers"})
        res = client.post("/portfolios", headers=auth_headers, json={"name": "keepers"})
        assert res.status_code == 409

    def test_rename(self, client, auth_headers):
        pid = client.post("/portfolios", headers=auth_headers, json={"name": "Old"}).json()["id"]
        assert client.patch(f"/portfolios/{pid}", headers=auth_headers, json={"name": "New"}).status_code == 200
        assert "New" in names(client.get("/portfolios", headers=auth_headers).json())

    def test_rename_to_existing_name_rejected(self, client, auth_headers):
        client.post("/portfolios", headers=auth_headers, json={"name": "A"})
        pid = client.post("/portfolios", headers=auth_headers, json={"name": "B"}).json()["id"]
        assert client.patch(f"/portfolios/{pid}", headers=auth_headers, json={"name": "A"}).status_code == 409

    def test_rename_to_same_name_is_fine(self, client, auth_headers):
        pid = client.post("/portfolios", headers=auth_headers, json={"name": "Keepers"}).json()["id"]
        assert client.patch(f"/portfolios/{pid}", headers=auth_headers, json={"name": "Keepers"}).status_code == 200

    def test_delete_empty_portfolio(self, client, auth_headers):
        pid = client.post("/portfolios", headers=auth_headers, json={"name": "Temp"}).json()["id"]
        assert client.delete(f"/portfolios/{pid}", headers=auth_headers).status_code == 200
        assert "Temp" not in names(client.get("/portfolios", headers=auth_headers).json())

    def test_cannot_delete_last_portfolio(self, client, auth_headers):
        [only] = client.get("/portfolios", headers=auth_headers).json()
        res = client.delete(f"/portfolios/{only['id']}", headers=auth_headers)
        assert res.status_code == 400
        assert "only portfolio" in res.json()["detail"]

    def test_delete_removes_its_cards(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4", price=500.0))
        pid = client.post("/portfolios", headers=auth_headers, json={"name": "Trade"}).json()["id"]
        client.post("/portfolio/add", headers=auth_headers,
                    json={"card_id": "base1-4", "purchase_price": 10.0, "portfolio_id": pid})
        assert len(client.get("/portfolio", headers=auth_headers).json()) == 1
        client.delete(f"/portfolios/{pid}", headers=auth_headers)
        # The lot in the deleted portfolio is gone (account-wide list is empty)
        assert client.get("/portfolio", headers=auth_headers).json() == []


class TestOwnership:
    def test_cannot_see_or_touch_another_users_portfolio(self, client, auth_headers, second_auth_headers):
        pid = client.post("/portfolios", headers=auth_headers, json={"name": "Mine"}).json()["id"]
        assert client.get(f"/portfolio?portfolio_id={pid}", headers=second_auth_headers).status_code == 404
        assert client.patch(f"/portfolios/{pid}", headers=second_auth_headers, json={"name": "x"}).status_code == 404
        assert client.delete(f"/portfolios/{pid}", headers=second_auth_headers).status_code == 404

    def test_add_to_unowned_portfolio_rejected(self, client, auth_headers, second_auth_headers, upstream):
        upstream.add(make_card("base1-4", price=500.0))
        pid = client.post("/portfolios", headers=auth_headers, json={"name": "Mine"}).json()["id"]
        res = client.post("/portfolio/add", headers=second_auth_headers,
                          json={"card_id": "base1-4", "purchase_price": 10.0, "portfolio_id": pid})
        assert res.status_code == 404


class TestScopedAddAndList:
    def test_add_targets_the_chosen_portfolio(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4", "Charizard", price=500.0))
        upstream.add(make_card("base1-58", "Pikachu", price=5.0))
        [default] = client.get("/portfolios", headers=auth_headers).json()
        trade = client.post("/portfolios", headers=auth_headers, json={"name": "Trade"}).json()

        client.post("/portfolio/add", headers=auth_headers,
                    json={"card_id": "base1-4", "purchase_price": 10.0})  # → default
        client.post("/portfolio/add", headers=auth_headers,
                    json={"card_id": "base1-58", "purchase_price": 1.0, "portfolio_id": trade["id"]})

        default_cards = client.get(f"/portfolio?portfolio_id={default['id']}", headers=auth_headers).json()
        trade_cards = client.get(f"/portfolio?portfolio_id={trade['id']}", headers=auth_headers).json()
        assert [c["card_id"] for c in default_cards] == ["base1-4"]
        assert [c["card_id"] for c in trade_cards] == ["base1-58"]
        # No portfolio_id = every lot across both portfolios (owned-badge relies on this)
        assert len(client.get("/portfolio", headers=auth_headers).json()) == 2

    def test_batch_add_targets_the_chosen_portfolio(self, client, auth_headers, upstream):
        # batch resolves names from the catalog, so seed it there
        from app.services import card_catalog
        from conftest import TestingSessionLocal
        db = TestingSessionLocal()
        card_catalog.upsert_cards(db, [make_card("base1-4", "Charizard", price=500.0)])
        db.close()

        trade = client.post("/portfolios", headers=auth_headers, json={"name": "Trade"}).json()
        res = client.post("/portfolio/add-batch", headers=auth_headers, json={
            "items": [{"card_id": "base1-4", "purchase_price": 10.0, "quantity": 1}],
            "portfolio_id": trade["id"],
        })
        assert res.json()["added"] == 1
        trade_cards = client.get(f"/portfolio?portfolio_id={trade['id']}", headers=auth_headers).json()
        assert [c["card_id"] for c in trade_cards] == ["base1-4"]

    def test_history_scoped_to_portfolio(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4", price=500.0))
        trade = client.post("/portfolios", headers=auth_headers, json={"name": "Trade"}).json()
        client.post("/portfolio/add", headers=auth_headers,
                    json={"card_id": "base1-4", "purchase_price": 10.0, "portfolio_id": trade["id"]})
        # Loading the portfolio records today's price snapshot (history reads from it)
        client.get(f"/portfolio?portfolio_id={trade['id']}", headers=auth_headers)
        # The default portfolio holds nothing, so its history is empty
        [default, _] = client.get("/portfolios", headers=auth_headers).json()
        assert client.get(f"/portfolio/history?portfolio_id={default['id']}", headers=auth_headers).json() == []
        # The trade portfolio has a held card → its history has points
        assert len(client.get(f"/portfolio/history?portfolio_id={trade['id']}", headers=auth_headers).json()) >= 1
