"""Rate limiting: the sliding-window dependency itself, plus the live limits
on the auth endpoints (login is the brute-force target). conftest's autouse
fresh_rate_limits fixture resets counters between tests, so each test starts
with a clean budget."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.services import rate_limit as rl


def make_request(ip: str = "203.0.113.9", headers: dict[str, str] | None = None) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "client": (ip, 51234),
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    })


# ---- The dependency ---------------------------------------------------------

def test_allows_up_to_limit_then_429():
    dep = rl.rate_limit("t-basic", times=3, seconds=60)
    for _ in range(3):
        dep(make_request())
    with pytest.raises(HTTPException) as exc:
        dep(make_request())
    assert exc.value.status_code == 429
    assert "try again" in exc.value.detail
    assert 1 <= int(exc.value.headers["Retry-After"]) <= 60


def test_window_slides(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(rl, "_now", lambda: clock[0])
    dep = rl.rate_limit("t-window", times=2, seconds=60)
    dep(make_request())
    dep(make_request())
    with pytest.raises(HTTPException):
        dep(make_request())
    clock[0] += 61  # the first two hits age out of the window
    dep(make_request())


def test_scopes_and_ips_are_independent():
    dep_a = rl.rate_limit("t-scope-a", times=1, seconds=60)
    dep_b = rl.rate_limit("t-scope-b", times=1, seconds=60)
    dep_a(make_request(ip="1.1.1.1"))
    with pytest.raises(HTTPException):
        dep_a(make_request(ip="1.1.1.1"))
    dep_a(make_request(ip="2.2.2.2"))  # other client: fresh budget
    dep_b(make_request(ip="1.1.1.1"))  # other scope: fresh budget


def test_shared_scope_shares_one_budget():
    # Two routers registering the same scope (like cards + portfolio's "api")
    # draw from a single allowance
    dep1 = rl.rate_limit("t-shared", times=2, seconds=60)
    dep2 = rl.rate_limit("t-shared", times=2, seconds=60)
    dep1(make_request())
    dep2(make_request())
    with pytest.raises(HTTPException):
        dep1(make_request())


def test_conflicting_scope_params_rejected():
    rl.rate_limit("t-conflict", times=5, seconds=60)
    with pytest.raises(ValueError):
        rl.rate_limit("t-conflict", times=6, seconds=60)


def test_forwarded_header_ignored_unless_trusted(monkeypatch):
    spoofed = make_request(ip="9.9.9.9", headers={"X-Forwarded-For": "10.0.0.1, 172.16.0.1"})
    assert rl.client_ip(spoofed) == "9.9.9.9"
    monkeypatch.setattr(rl, "_TRUST_FORWARDED", True)
    assert rl.client_ip(spoofed) == "10.0.0.1"


def test_reset_clears_counters():
    dep = rl.rate_limit("t-reset", times=1, seconds=60)
    dep(make_request())
    rl.reset()
    dep(make_request())


# ---- Live limits on the auth routes ----------------------------------------

def test_login_locks_out_after_repeated_attempts(client):
    for _ in range(10):
        res = client.post("/auth/login", data={"username": "ash", "password": "wrong-pw1"})
        assert res.status_code == 401
    res = client.post("/auth/login", data={"username": "ash", "password": "wrong-pw1"})
    assert res.status_code == 429
    assert "Retry-After" in res.headers
    assert "login attempts" in res.json()["detail"]


def test_login_limit_blocks_even_correct_password(client):
    # Brute-forcers don't get a free pass on the guess that happens to be right
    client.post("/auth/register", json={
        "email": "misty@example.com", "username": "misty", "password": "starmie1",
        "accepted_terms": True,
    })
    for _ in range(10):
        client.post("/auth/login", data={"username": "misty", "password": "wrong-pw1"})
    res = client.post("/auth/login", data={"username": "misty", "password": "starmie1"})
    assert res.status_code == 429


def test_register_rate_limited(client):
    for i in range(10):
        res = client.post("/auth/register", json={
            "email": f"u{i}@example.com", "username": f"user{i}", "password": "password1",
            "accepted_terms": True,
        })
        assert res.status_code == 200
    res = client.post("/auth/register", json={
        "email": "u10@example.com", "username": "user10", "password": "password1",
        "accepted_terms": True,
    })
    assert res.status_code == 429
    assert "signup attempts" in res.json()["detail"]
