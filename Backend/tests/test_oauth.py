"""Social sign-in (OAuth/OIDC) — the merge/link resolver, config gating, the
start redirect, and the callback end to end. The provider HTTP (token exchange +
JWKS verification) is monkeypatched at the `oauth.complete_login` seam, so these
run offline like the rest of the suite."""

import re
import time

import pytest

from app.models import User, OAuthAccount
from app.routers.auth import resolve_oauth_user
from app.services import mailer, oauth
from app.services.oauth import OAuthIdentity, OAuthError
from conftest import TestingSessionLocal


def ident(provider="google", sub="sub-1", email="ash@example.com",
          verified=True, name="Ash Ketchum") -> OAuthIdentity:
    return OAuthIdentity(provider=provider, sub=sub, email=email,
                         email_verified=verified, name=name)


def register(client, email, username, password="pikachu1"):
    return client.post("/auth/register", json={
        "email": email, "username": username, "password": password,
        "accepted_terms": True})


def seed_pending(state="teststate", provider="google") -> str:
    """Register a pending login as /start would, so a callback can consume it."""
    oauth._pending[state] = {"provider": provider, "code_verifier": "v",
                             "nonce": "n", "created_at": time.time()}
    return state


@pytest.fixture(autouse=True)
def clear_pending():
    oauth._pending.clear()
    yield
    oauth._pending.clear()


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "csecret")


# ----- The merge / link resolver ---------------------------------------------

class TestResolveOAuthUser:
    def test_creates_new_verified_account(self):
        db = TestingSessionLocal()
        try:
            user, is_new = resolve_oauth_user(db, ident(email="new@example.com"))
            assert is_new is True
            assert user.email == "new@example.com"
            assert user.hashed_password is None          # social-only
            assert user.email_verified_at is not None    # provider-verified
            assert user.accepted_terms_at is not None    # button carries the terms line
            assert user.username                          # generated, non-empty
            links = db.query(OAuthAccount).filter_by(user_id=user.id).all()
            assert [l.provider for l in links] == ["google"]
            assert links[0].provider_account_id == "sub-1"
        finally:
            db.close()

    def test_returning_user_by_sub_does_not_duplicate(self):
        db = TestingSessionLocal()
        try:
            u1, new1 = resolve_oauth_user(db, ident(sub="abc", email="a@example.com"))
            u2, new2 = resolve_oauth_user(db, ident(sub="abc", email="a@example.com"))
            assert new1 is True and new2 is False
            assert u1.id == u2.id
            assert db.query(OAuthAccount).count() == 1   # linked once, not twice
            assert db.query(User).count() == 1
        finally:
            db.close()

    def test_merges_into_existing_password_account(self, client):
        register(client, "merge@example.com", "merger")
        db = TestingSessionLocal()
        try:
            existing = db.query(User).filter_by(email="merge@example.com").first()
            assert existing.email_verified_at is None    # register leaves it soft
            user, is_new = resolve_oauth_user(
                db, ident(sub="g-1", email="merge@example.com"))
            assert is_new is False
            assert user.id == existing.id                 # merged, not duplicated
            assert db.query(User).filter_by(email="merge@example.com").count() == 1
            assert user.hashed_password is not None       # keeps its password
            assert user.email_verified_at is not None     # merge confirms the email
            link = db.query(OAuthAccount).filter_by(user_id=existing.id).one()
            assert link.provider == "google" and link.provider_account_id == "g-1"
        finally:
            db.close()

    def test_username_is_deduped(self, client):
        register(client, "taken@example.com", "ash")
        db = TestingSessionLocal()
        try:
            # derived base "ash" (from name "Ash") collides with the existing user
            user, is_new = resolve_oauth_user(
                db, ident(sub="g2", email="fresh@example.com", name="Ash"))
            assert is_new is True
            assert user.username != "ash"
            assert user.username.startswith("ash")
        finally:
            db.close()

    def test_unverified_email_colliding_is_refused(self, client):
        register(client, "victim@example.com", "victim")
        db = TestingSessionLocal()
        try:
            with pytest.raises(OAuthError) as exc:
                resolve_oauth_user(
                    db, ident(sub="attacker", email="victim@example.com", verified=False))
            assert exc.value.code == "email_unverified"
            # no takeover: no link created, no duplicate user
            assert db.query(OAuthAccount).count() == 0
            assert db.query(User).filter_by(email="victim@example.com").count() == 1
        finally:
            db.close()

    def test_unverified_email_without_collision_creates_unverified_account(self):
        db = TestingSessionLocal()
        try:
            user, is_new = resolve_oauth_user(
                db, ident(sub="g3", email="lonely@example.com", verified=False))
            assert is_new is True
            assert user.email_verified_at is None
        finally:
            db.close()


# ----- Config gating: only configured providers are offered ------------------

class TestProvidersEndpoint:
    def test_none_configured_by_default(self, client):
        res = client.get("/auth/oauth/providers")
        assert res.status_code == 200
        assert res.json() == {"providers": []}

    def test_reflects_configured_provider(self, client, google):
        res = client.get("/auth/oauth/providers")
        assert res.json()["providers"] == ["google"]


# ----- /start: redirect to the provider (or 404 when unavailable) ------------

class TestOAuthStart:
    def test_unconfigured_provider_404s(self, client):
        res = client.get("/auth/oauth/google/start", follow_redirects=False)
        assert res.status_code == 404

    def test_unknown_provider_404s(self, client, google):
        res = client.get("/auth/oauth/bogus/start", follow_redirects=False)
        assert res.status_code == 404

    def test_redirects_to_provider_with_pkce_and_state(self, client, google):
        res = client.get("/auth/oauth/google/start", follow_redirects=False)
        assert res.status_code == 302
        loc = res.headers["location"]
        assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "client_id=cid" in loc
        assert "code_challenge=" in loc and "code_challenge_method=S256" in loc
        state = re.search(r"[?&]state=([^&]+)", loc).group(1)
        assert state in oauth._pending  # a pending login was recorded


# ----- /callback: identity -> our JWT (or an error redirect) -----------------

class TestOAuthCallback:
    def _cb(self, client, state, **params):
        qs = "&".join(f"{k}={v}" for k, v in {"state": state, **params}.items())
        return client.get(f"/auth/oauth/google/callback?{qs}", follow_redirects=False)

    def test_creates_account_and_returns_working_token(self, client, monkeypatch):
        state = seed_pending()
        monkeypatch.setattr(oauth, "complete_login",
                            lambda *a, **k: ident(sub="cb", email="cb@example.com"))
        res = self._cb(client, state, code="abc")
        assert res.status_code == 302
        loc = res.headers["location"]
        assert loc.startswith("http://localhost:5173/auth/callback#token=")
        token = loc.split("#token=")[1]
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        body = me.json()
        assert body["email"] == "cb@example.com"
        assert body["has_password"] is False
        assert body["oauth_providers"] == ["google"]

    def test_state_is_single_use(self, client, monkeypatch):
        state = seed_pending()
        monkeypatch.setattr(oauth, "complete_login",
                            lambda *a, **k: ident(sub="cb2", email="cb2@example.com"))
        assert self._cb(client, state, code="abc").status_code == 302
        # reusing the same state now fails (it was consumed)
        again = self._cb(client, state, code="abc")
        assert "oauth_error=expired" in again.headers["location"]

    def test_unknown_state_redirects_expired(self, client):
        res = self._cb(client, "nope", code="abc")
        assert res.status_code == 302
        assert "oauth_error=expired" in res.headers["location"]

    def test_provider_error_redirects_with_code(self, client, monkeypatch):
        state = seed_pending()

        def boom(*a, **k):
            raise OAuthError("email_unverified")

        monkeypatch.setattr(oauth, "complete_login", boom)
        res = self._cb(client, state, code="abc")
        assert "oauth_error=email_unverified" in res.headers["location"]

    def test_user_cancelled_redirects_cancelled(self, client):
        res = self._cb(client, "x", error="access_denied")
        assert "oauth_error=cancelled" in res.headers["location"]


# ----- Password-less accounts don't hit broken password paths ----------------

class TestPasswordlessGuards:
    def _social_token(self, client, monkeypatch, email="soc@example.com", sub="s"):
        state = seed_pending(state=f"st-{sub}")
        monkeypatch.setattr(oauth, "complete_login",
                            lambda *a, **k: ident(sub=sub, email=email))
        res = client.get(f"/auth/oauth/google/callback?code=c&state=st-{sub}",
                         follow_redirects=False)
        return res.headers["location"].split("#token=")[1]

    def test_password_login_rejected_for_social_only(self, client):
        db = TestingSessionLocal()
        try:
            resolve_oauth_user(db, ident(sub="s1", email="social@example.com"))
        finally:
            db.close()
        res = client.post("/auth/login",
                          data={"username": "social@example.com", "password": "anything1"})
        assert res.status_code == 401

    def test_change_password_blocked_for_social_only(self, client, monkeypatch):
        token = self._social_token(client, monkeypatch, "soc2@example.com", "s2")
        res = client.post("/auth/me/password",
                          headers={"Authorization": f"Bearer {token}"},
                          json={"current_password": "x", "new_password": "newpass12"})
        assert res.status_code == 400
        assert "social sign-in" in res.json()["detail"]

    def test_social_user_can_set_password_via_reset_then_login(self, client, monkeypatch):
        messages: list[dict] = []
        monkeypatch.setattr(mailer, "send_email",
                            lambda to, subject, body, html=None:
                            messages.append({"to": to, "body": body}))
        # a social-only account with a verified email
        db = TestingSessionLocal()
        try:
            resolve_oauth_user(db, ident(sub="s3", email="soc3@example.com"))
        finally:
            db.close()
        client.post("/auth/forgot-password", json={"email": "soc3@example.com"})
        reset_mail = [m for m in messages if "/reset-password?token=" in m["body"]][-1]
        raw = re.search(r"token=([A-Za-z0-9_-]+)", reset_mail["body"]).group(1)
        assert client.post("/auth/reset-password",
                           json={"token": raw, "new_password": "brandnew1"}).status_code == 200
        # now password login works for the once-social account
        res = client.post("/auth/login",
                          data={"username": "soc3@example.com", "password": "brandnew1"})
        assert res.status_code == 200
        assert "access_token" in res.json()
