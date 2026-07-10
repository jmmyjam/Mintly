REGISTER = {"email": "ash@example.com", "username": "ash", "password": "pikachu1"}


def register(client, **overrides):
    return client.post("/auth/register", json={**REGISTER, **overrides})


class TestRegister:
    def test_success(self, client):
        res = register(client)
        assert res.status_code == 200
        assert res.json() == {"message": "Account created"}

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
