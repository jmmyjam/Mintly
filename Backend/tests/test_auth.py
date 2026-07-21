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


class TestGetMe:
    def test_requires_auth(self, client):
        assert client.get("/auth/me").status_code == 401

    def test_returns_profile(self, client, auth_headers):
        res = client.get("/auth/me", headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["email"] == "ash@example.com"
        assert body["username"] == "ash"
        assert body["created_at"]
        # never leak the password hash
        assert "hashed_password" not in body


class TestUpdateProfile:
    def test_requires_auth(self, client):
        assert client.patch("/auth/me", json={"username": "new"}).status_code == 401

    def test_update_username(self, client, auth_headers):
        res = client.patch("/auth/me", json={"username": "ashketchum"}, headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["username"] == "ashketchum"
        # the new username logs in
        login = client.post("/auth/login", data={"username": "ashketchum", "password": "pikachu1"})
        assert login.status_code == 200

    def test_update_email(self, client, auth_headers):
        res = client.patch("/auth/me", json={"email": "ash2@example.com"}, headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["email"] == "ash2@example.com"

    def test_duplicate_username_rejected(self, client, auth_headers, second_auth_headers):
        res = client.patch("/auth/me", json={"username": "gary"}, headers=auth_headers)
        assert res.status_code == 409
        assert res.json()["detail"] == "Username already taken"

    def test_duplicate_email_rejected(self, client, auth_headers, second_auth_headers):
        res = client.patch("/auth/me", json={"email": "gary@example.com"}, headers=auth_headers)
        assert res.status_code == 409
        assert res.json()["detail"] == "Email already registered"

    def test_keeping_own_values_is_ok(self, client, auth_headers):
        # re-saving your current username/email is not a duplicate conflict
        res = client.patch("/auth/me",
                           json={"username": "ash", "email": "ash@example.com"},
                           headers=auth_headers)
        assert res.status_code == 200

    def test_invalid_email_rejected(self, client, auth_headers):
        res = client.patch("/auth/me", json={"email": "notanemail"}, headers=auth_headers)
        assert res.status_code == 400

    def test_blank_username_rejected(self, client, auth_headers):
        res = client.patch("/auth/me", json={"username": "   "}, headers=auth_headers)
        assert res.status_code == 400

    def test_empty_body_is_noop(self, client, auth_headers):
        res = client.patch("/auth/me", json={}, headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["username"] == "ash"


class TestChangePassword:
    def test_requires_auth(self, client):
        res = client.post("/auth/me/password",
                          json={"current_password": "x", "new_password": "newpass123"})
        assert res.status_code == 401

    def test_wrong_current_password(self, client, auth_headers):
        res = client.post("/auth/me/password",
                          json={"current_password": "wrongpass1", "new_password": "newpass123"},
                          headers=auth_headers)
        assert res.status_code == 400
        assert res.json()["detail"] == "Current password is incorrect"

    def test_weak_new_password(self, client, auth_headers):
        res = client.post("/auth/me/password",
                          json={"current_password": "pikachu1", "new_password": "short"},
                          headers=auth_headers)
        assert res.status_code == 400
        assert res.json()["detail"] == "Password must be at least 8 characters"

    def test_success_swaps_password(self, client, auth_headers):
        res = client.post("/auth/me/password",
                          json={"current_password": "pikachu1", "new_password": "newpass123"},
                          headers=auth_headers)
        assert res.status_code == 200
        assert res.json() == {"message": "Password updated"}
        # old password no longer works, new one does
        assert client.post("/auth/login", data={"username": "ash", "password": "pikachu1"}).status_code == 401
        assert client.post("/auth/login", data={"username": "ash", "password": "newpass123"}).status_code == 200


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
