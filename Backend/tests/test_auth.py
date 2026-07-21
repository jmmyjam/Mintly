from app.models import PortfolioCard
from conftest import TestingSessionLocal, make_card

REGISTER = {"email": "ash@example.com", "username": "ash", "password": "pikachu1",
            "accepted_terms": True}


def register(client, **overrides):
    return client.post("/auth/register", json={**REGISTER, **overrides})


class TestRegister:
    def test_success(self, client):
        res = register(client)
        assert res.status_code == 200
        assert res.json() == {"message": "Account created"}

    def test_terms_must_be_accepted(self, client):
        res = register(client, accepted_terms=False)
        assert res.status_code == 400
        assert res.json()["detail"] == "You must agree to the Terms of Service"

    def test_terms_default_is_not_accepted(self, client):
        payload = {k: v for k, v in REGISTER.items() if k != "accepted_terms"}
        res = client.post("/auth/register", json=payload)
        assert res.status_code == 400

    def test_password_too_short(self, client):
        res = register(client, password="ab1")
        assert res.status_code == 400
        assert res.json()["detail"] == "Password must be at least 8 characters"

    def test_password_needs_letter(self, client):
        res = register(client, password="12345678")
        assert res.status_code == 400
        assert res.json()["detail"] == "Password must contain at least one letter"

    def test_password_needs_number(self, client):
        res = register(client, password="abcdefgh")
        assert res.status_code == 400
        assert res.json()["detail"] == "Password must contain at least one number"

    def test_duplicate_email(self, client):
        register(client)
        res = register(client, username="other")
        assert res.status_code == 409
        assert res.json()["detail"] == "Email already registered"

    def test_duplicate_username(self, client):
        register(client)
        res = register(client, email="other@example.com")
        assert res.status_code == 409
        assert res.json()["detail"] == "Username already taken"


class TestLogin:
    def test_login_with_username(self, client):
        register(client)
        res = client.post("/auth/login", data={"username": "ash", "password": "pikachu1"})
        assert res.status_code == 200
        body = res.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]

    def test_login_with_email(self, client):
        register(client)
        res = client.post("/auth/login", data={"username": "ash@example.com", "password": "pikachu1"})
        assert res.status_code == 200
        assert res.json()["access_token"]

    def test_wrong_password(self, client):
        register(client)
        res = client.post("/auth/login", data={"username": "ash", "password": "wrongpass1"})
        assert res.status_code == 401

    def test_unknown_user(self, client):
        res = client.post("/auth/login", data={"username": "nobody", "password": "pikachu1"})
        assert res.status_code == 401


class TestDeleteAccount:
    def test_requires_auth(self, client):
        assert client.delete("/auth/me").status_code == 401

    def test_deletes_account(self, client, auth_headers):
        res = client.delete("/auth/me", headers=auth_headers)
        assert res.status_code == 200
        assert res.json() == {"message": "Account deleted"}

    def test_token_stops_working_after_delete(self, client, auth_headers):
        client.delete("/auth/me", headers=auth_headers)
        # the JWT now points at a deleted user
        assert client.get("/portfolio", headers=auth_headers).status_code == 401

    def test_email_and_username_freed(self, client, auth_headers):
        client.delete("/auth/me", headers=auth_headers)
        # re-registering the same credentials succeeds — the account is really gone
        assert register(client).status_code == 200

    def test_deletes_portfolio_cards(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4", "Charizard", price=500.0))
        add = client.post("/portfolio/add",
                          json={"card_id": "base1-4", "quantity": 2},
                          headers=auth_headers)
        assert add.status_code == 200
        db = TestingSessionLocal()
        assert db.query(PortfolioCard).count() == 1
        db.close()

        client.delete("/auth/me", headers=auth_headers)

        db = TestingSessionLocal()
        assert db.query(PortfolioCard).count() == 0
        db.close()

    def test_only_deletes_own_account(self, client, auth_headers, second_auth_headers):
        client.delete("/auth/me", headers=auth_headers)
        # the other user is untouched
        assert client.get("/portfolio", headers=second_auth_headers).status_code == 200


class TestTokenValidation:
    def test_missing_token(self, client):
        assert client.get("/portfolio").status_code == 401

    def test_garbage_token(self, client):
        res = client.get("/portfolio", headers={"Authorization": "Bearer not-a-jwt"})
        assert res.status_code == 401

    def test_valid_token_grants_access(self, client, auth_headers):
        res = client.get("/portfolio", headers=auth_headers)
        assert res.status_code == 200
        assert res.json() == []
