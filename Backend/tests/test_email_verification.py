"""Email verification flow — soft verification (register sends a link; the app
is usable unverified; Profile shows the state + resend)."""
import re

import pytest

from app.services import mailer

REGISTER = {"email": "ash@example.com", "username": "ash", "password": "pikachu1",
            "accepted_terms": True}


@pytest.fixture
def sent(monkeypatch):
    """Capture outbound emails instead of sending (auth.py resolves
    mailer.send_email at call time, so patching the module attr works)."""
    messages: list[dict] = []

    def capture(to, subject, body, html=None):
        messages.append({"to": to, "subject": subject, "body": body, "html": html})

    monkeypatch.setattr(mailer, "send_email", capture)
    return messages


def verify_mails(messages) -> list[dict]:
    return [m for m in messages if "/verify-email?token=" in m["body"]]


def verify_token(messages) -> str:
    """Raw token out of the most recent verification email."""
    return re.search(r"/verify-email\?token=([A-Za-z0-9_-]+)",
                     verify_mails(messages)[-1]["body"]).group(1)


def register(client):
    return client.post("/auth/register", json=REGISTER)


def login(client):
    res = client.post("/auth/login", data={"username": "ash", "password": "pikachu1"})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


class TestVerificationEmail:
    def test_register_sends_verification_email(self, client, sent):
        register(client)
        mails = verify_mails(sent)
        assert len(mails) == 1
        assert mails[0]["to"] == "ash@example.com"
        assert mails[0]["subject"] == "Verify your Mintly email"
        assert "/verify-email?token=" in mails[0]["html"]  # HTML alt carries it too

    def test_new_account_is_unverified(self, client, sent):
        register(client)
        me = client.get("/auth/me", headers=login(client)).json()
        assert me["email_verified"] is False

    def test_verify_marks_account_verified(self, client, sent):
        register(client)
        headers = login(client)
        res = client.post("/auth/verify-email", json={"token": verify_token(sent)})
        assert res.status_code == 200
        assert client.get("/auth/me", headers=headers).json()["email_verified"] is True

    def test_verify_works_without_auth(self, client, sent):
        # the link from the email must work whether or not a browser is logged in
        register(client)
        assert client.post("/auth/verify-email",
                           json={"token": verify_token(sent)}).status_code == 200

    def test_verify_is_single_use(self, client, sent):
        register(client)
        token = verify_token(sent)
        assert client.post("/auth/verify-email", json={"token": token}).status_code == 200
        assert client.post("/auth/verify-email", json={"token": token}).status_code == 400

    def test_verify_rejects_garbage_token(self, client, sent):
        register(client)
        assert client.post("/auth/verify-email",
                           json={"token": "not-a-real-token"}).status_code == 400

    def test_resend_supersedes_old_link(self, client, sent):
        register(client)
        headers = login(client)
        old = verify_token(sent)
        assert client.post("/auth/verify-email/send", headers=headers).status_code == 200
        new = verify_token(sent)
        assert new != old
        # only the newest link works
        assert client.post("/auth/verify-email", json={"token": old}).status_code == 400
        assert client.post("/auth/verify-email", json={"token": new}).status_code == 200

    def test_resend_is_noop_once_verified(self, client, sent):
        register(client)
        headers = login(client)
        client.post("/auth/verify-email", json={"token": verify_token(sent)})
        before = len(verify_mails(sent))
        res = client.post("/auth/verify-email/send", headers=headers)
        assert res.status_code == 200
        assert "already verified" in res.json()["message"].lower()
        assert len(verify_mails(sent)) == before  # no new email sent

    def test_resend_requires_auth(self, client, sent):
        assert client.post("/auth/verify-email/send").status_code == 401

    def test_changing_email_resets_verification(self, client, sent):
        register(client)
        headers = login(client)
        client.post("/auth/verify-email", json={"token": verify_token(sent)})
        # swap the address → unverified again + a fresh verification email to it
        res = client.patch("/auth/me", json={"email": "new@example.com"}, headers=headers)
        assert res.status_code == 200
        assert res.json()["email_verified"] is False
        assert verify_mails(sent)[-1]["to"] == "new@example.com"
