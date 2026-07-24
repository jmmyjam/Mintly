"""Admin stats endpoint: the ADMIN_EMAILS gate and the aggregate numbers."""

from datetime import timedelta

from conftest import TestingSessionLocal, make_card

from app.models import User, utcnow
from app.services import admin_access, card_catalog


def grant_admin(monkeypatch, email="ash@example.com"):
    monkeypatch.setattr(admin_access, "_ADMIN_EMAILS", {email})


# ----- Gating ----------------------------------------------------------------

def test_stats_require_auth(client):
    assert client.get("/admin/stats").status_code == 401


def test_non_admin_gets_404(client, auth_headers):
    # 404, not 403 — the endpoint's existence isn't advertised to non-admins
    res = client.get("/admin/stats", headers=auth_headers)
    assert res.status_code == 404


def test_admin_gets_stats(client, auth_headers, monkeypatch):
    grant_admin(monkeypatch)
    res = client.get("/admin/stats", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["users"]["total"] == 1
    assert body["signups_by_day"][-1]["count"] == 1  # registered today


def test_admin_email_match_is_case_insensitive(monkeypatch):
    grant_admin(monkeypatch)
    assert admin_access.is_admin(User(email="ASH@Example.com"))
    assert not admin_access.is_admin(User(email="gary@example.com"))
    assert not admin_access.is_admin(User(email=None))


def test_me_carries_admin_flag(client, auth_headers, monkeypatch):
    assert client.get("/auth/me", headers=auth_headers).json()["is_admin"] is False
    grant_admin(monkeypatch)
    assert client.get("/auth/me", headers=auth_headers).json()["is_admin"] is True


# ----- The numbers -----------------------------------------------------------

def test_stats_counts(client, auth_headers, second_auth_headers, upstream, monkeypatch):
    grant_admin(monkeypatch)
    upstream.add(make_card("base1-4", "Charizard", price=500.0))
    upstream.add(make_card("base1-58", "Pikachu", price=5.0))
    # ash: two lots (one card twice = still 2 lots, 1 distinct card among ash's)
    client.post("/portfolio/add", headers=auth_headers,
                json={"card_id": "base1-4", "purchase_price": 400.0, "quantity": 2})
    client.post("/portfolio/add", headers=auth_headers,
                json={"card_id": "base1-58", "purchase_price": 3.0, "quantity": 1})
    # gary: no portfolio

    body = client.get("/admin/stats", headers=auth_headers).json()

    assert body["users"] == {
        "total": 2, "new_7d": 2, "new_30d": 2, "with_portfolio": 1,
    }
    assert body["portfolio"] == {
        "lots": 2, "distinct_cards": 2, "total_quantity": 3,
    }
    # newest first; lot counts ride along
    lots_by_name = {u["username"]: u["lots"] for u in body["recent_users"]}
    assert lots_by_name == {"ash": 2, "gary": 0}
    # SQLite has no pg_database_size — the field degrades to null, never a 500
    assert body["db_size_bytes"] is None


def test_signup_window_excludes_old_accounts(client, auth_headers, monkeypatch):
    grant_admin(monkeypatch)
    db = TestingSessionLocal()
    db.add(User(email="old@example.com", username="old",
                hashed_password="x", created_at=utcnow() - timedelta(days=90)))
    db.commit()
    db.close()

    body = client.get("/admin/stats", headers=auth_headers).json()
    assert body["users"]["total"] == 2
    assert body["users"]["new_30d"] == 1
    assert sum(day["count"] for day in body["signups_by_day"]) == 1
    assert len(body["signups_by_day"]) == 30


def test_catalog_and_snapshot_stats(client, auth_headers, monkeypatch):
    grant_admin(monkeypatch)
    db = TestingSessionLocal()
    card_catalog.upsert_cards(db, [make_card("base1-4", "Charizard", price=500.0)])
    card_catalog.mark_full_sync(db)
    db.close()

    body = client.get("/admin/stats", headers=auth_headers).json()
    assert body["catalog"]["cards"] == 1
    assert body["catalog"]["stale_prices"] == 0
    assert body["catalog"]["last_full_sync"] is not None
