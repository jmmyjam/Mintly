import re
from datetime import timedelta

import pytest

from app.models import PasswordResetToken, utcnow
from app.services import mailer
from conftest import TestingSessionLocal

REGISTER = {"email": "ash@example.com", "username": "ash", "password": "pikachu1",
            "accepted_terms": True}

GENERIC = "If that email has an account, a reset link is on its way."
INVALID = "This reset link is invalid or has expired — request a new one"


@pytest.fixture
def sent(monkeypatch):
    """Capture outbound emails instead of sending (auth.py resolves
    mailer.send_email at call time, so patching the module attr works)."""
    messages: list[dict] = []

    def capture(to, subject, body, html=None):
        messages.append({"to": to, "subject": subject, "body": body, "html": html})

    monkeypatch.setattr(mailer, "send_email", capture)
    return messages


def register(client):
    client.post("/auth/register", json=REGISTER)


def request_reset(client, email="ash@example.com"):
    return client.post("/auth/forgot-password", json={"email": email})


def token_from(messages) -> str:
    """The raw token out of the most recent email's reset link."""
    return re.search(r"token=([A-Za-z0-9_-]+)", messages[-1]["body"]).group(1)


def reset(client, token, new_password="newpass123"):
    return client.post("/auth/reset-password",
                       json={"token": token, "new_password": new_password})


class TestForgotPassword:
    def test_known_email_sends_link(self, client, sent):
        register(client)
        res = request_reset(client)
        assert res.status_code == 200
        assert res.json() == {"message": GENERIC}
        assert len(sent) == 1
        assert sent[0]["to"] == "ash@example.com"
        assert "/reset-password?token=" in sent[0]["body"]
        # the HTML alternative carries the same link
        assert "/reset-password?token=" in sent[0]["html"]
        assert token_from(sent) in sent[0]["html"]

    def test_unknown_email_same_response_no_email(self, client, sent):
        register(client)
        known = request_reset(client)
        unknown = request_reset(client, email="nobody@example.com")
        # identical bodies — the endpoint must not confirm which emails exist
        assert unknown.status_code == known.status_code == 200
        assert unknown.json() == known.json()
        assert len(sent) == 1  # only the known address got mail

    def test_token_stored_hashed(self, client, sent):
        register(client)
        request_reset(client)
        raw = token_from(sent)
        db = TestingSessionLocal()
        rows = db.query(PasswordResetToken).all()
        assert len(rows) == 1
        assert rows[0].token_hash != raw and raw not in rows[0].token_hash
        db.close()

    def test_new_request_supersedes_old_link(self, client, sent):
        register(client)
        request_reset(client)
        old = token_from(sent)
        request_reset(client)
        new = token_from(sent)
        assert reset(client, old).status_code == 400
        assert reset(client, new).status_code == 200

    def test_username_escaped_in_html(self, client, sent):
        client.post("/auth/register", json={**REGISTER, "email": "ash2@example.com",
                                            "username": "<b>ash</b>"})
        request_reset(client, email="ash2@example.com")
        assert "<b>ash</b>" not in sent[-1]["html"]
        assert "&lt;b&gt;ash&lt;/b&gt;" in sent[-1]["html"]

    def test_send_failure_keeps_generic_response(self, client, monkeypatch):
        register(client)
        def boom(to, subject, body, html=None):
            raise RuntimeError("smtp down")
        monkeypatch.setattr(mailer, "send_email", boom)
        res = request_reset(client)
        assert res.status_code == 200
        assert res.json() == {"message": GENERIC}

    def test_rate_limited(self, client, sent):
        register(client)
        for _ in range(5):
            assert request_reset(client).status_code == 200
        res = request_reset(client)
        assert res.status_code == 429
        assert "Retry-After" in res.headers


class TestResetPassword:
    def test_resets_password(self, client, sent):
        register(client)
        request_reset(client)
        res = reset(client, token_from(sent))
        assert res.status_code == 200
        assert res.json() == {"message": "Password updated"}
        assert client.post("/auth/login", data={
            "username": "ash", "password": "pikachu1"}).status_code == 401
        assert client.post("/auth/login", data={
            "username": "ash", "password": "newpass123"}).status_code == 200

    def test_token_single_use(self, client, sent):
        register(client)
        request_reset(client)
        token = token_from(sent)
        assert reset(client, token).status_code == 200
        res = reset(client, token, new_password="another123")
        assert res.status_code == 400
        assert res.json()["detail"] == INVALID

    def test_expired_token(self, client, sent):
        register(client)
        request_reset(client)
        db = TestingSessionLocal()
        row = db.query(PasswordResetToken).one()
        row.expires_at = utcnow() - timedelta(minutes=1)
        db.commit(); db.close()
        res = reset(client, token_from(sent))
        assert res.status_code == 400
        assert res.json()["detail"] == INVALID

    def test_garbage_token(self, client):
        res = reset(client, "not-a-real-token")
        assert res.status_code == 400
        assert res.json()["detail"] == INVALID

    def test_weak_password_keeps_token_live(self, client, sent):
        register(client)
        request_reset(client)
        token = token_from(sent)
        res = reset(client, token, new_password="short")
        assert res.status_code == 400
        assert res.json()["detail"] == "Password must be at least 8 characters"
        # the rejected attempt didn't burn the link
        assert reset(client, token).status_code == 200


class TestCleanup:
    def test_delete_account_removes_pending_tokens(self, client, sent, auth_headers):
        # auth_headers registered "ash"; a pending reset must not block deletion
        request_reset(client)
        assert client.delete("/auth/me", headers=auth_headers).status_code == 200
        db = TestingSessionLocal()
        assert db.query(PasswordResetToken).count() == 0
        db.close()


class TestMailerFallback:
    def test_unconfigured_mailer_prints_instead_of_sending(self, monkeypatch, capsys):
        monkeypatch.setattr(mailer, "SMTP_HOST", "")
        mailer.send_email("ash@example.com", "Subject line", "Body text")
        out = capsys.readouterr().out
        assert "ash@example.com" in out and "Body text" in out
