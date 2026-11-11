"""Public feedback form: validation, the anti-spam layers, the notification
email, and the admin inbox (list + delete)."""

from datetime import timedelta

import pytest
from conftest import TestingSessionLocal

from app.models import Feedback, utcnow
from app.routers import feedback as feedback_module
from app.services import admin_access

GOOD = {"message": "Love the app, please add Japanese sets!", "elapsed_ms": 8000}


def stored() -> list[Feedback]:
    with TestingSessionLocal() as db:
        return db.query(Feedback).all()


@pytest.fixture
def sent(monkeypatch):
    """Capture notification emails (FEEDBACK_EMAIL is pinned empty by conftest)."""
    mails = []
    monkeypatch.setattr(feedback_module, "FEEDBACK_EMAIL", "ops@example.com")
    monkeypatch.setattr(feedback_module.mailer, "send_email",
                        lambda to, subject, body: mails.append((to, subject, body)))
    return mails


# ----- Accepting -------------------------------------------------------------

def test_anonymous_submission_is_stored(client):
    res = client.post("/feedback", json={**GOOD, "page": "/search"})
    assert res.status_code == 200
    assert res.json()["message"].startswith("Thanks")
    [row] = stored()
    assert row.message == GOOD["message"]
    assert row.email is None
    assert row.page == "/search"


def test_reply_email_is_kept(client):
    client.post("/feedback", json={**GOOD, "email": "  misty@example.com "})
    assert stored()[0].email == "misty@example.com"


def test_notification_email_carries_the_message(client, sent):
    client.post("/feedback", json={**GOOD, "email": "misty@example.com"})
    [(to, subject, body)] = sent
    assert to == "ops@example.com"
    assert GOOD["message"] in body
    assert "misty@example.com" in body


def test_mail_failure_does_not_fail_the_submission(client, monkeypatch):
    monkeypatch.setattr(feedback_module, "FEEDBACK_EMAIL", "ops@example.com")

    def boom(*args, **kwargs):
        raise OSError("smtp down")

    monkeypatch.setattr(feedback_module.mailer, "send_email", boom)
    assert client.post("/feedback", json=GOOD).status_code == 200
    assert len(stored()) == 1


# ----- Validation ------------------------------------------------------------

@pytest.mark.parametrize("message", ["too short", "   short   ", "x" * 2001])
def test_message_length_is_enforced(client, message):
    assert client.post("/feedback", json={**GOOD, "message": message}).status_code == 422
    assert stored() == []


def test_bad_email_is_rejected(client):
    res = client.post("/feedback", json={**GOOD, "email": "not-an-email"})
    assert res.status_code == 422


def test_link_spam_is_rejected(client):
    message = "buy now http://a.example http://b.example https://c.example www.d.example"
    res = client.post("/feedback", json={**GOOD, "message": message})
    assert res.status_code == 422
    assert "links" in res.json()["detail"]


def test_a_few_links_are_fine(client):
    message = "This card page is broken: https://mintlytcg.com/card/base1-4"
    assert client.post("/feedback", json={**GOOD, "message": message}).status_code == 200
    assert len(stored()) == 1


# ----- Silent drops (bot gets the normal success reply) ----------------------

def test_honeypot_is_silently_dropped(client, sent):
    res = client.post("/feedback", json={**GOOD, "website": "http://spam.example"})
    assert res.status_code == 200
    assert stored() == []
    assert sent == []


@pytest.mark.parametrize("elapsed", [None, 0, 2999])
def test_too_fast_or_missing_timer_is_silently_dropped(client, elapsed):
    body = {**GOOD, "elapsed_ms": elapsed}
    assert client.post("/feedback", json=body).status_code == 200
    assert stored() == []


def test_duplicate_message_is_stored_once(client, sent):
    client.post("/feedback", json=GOOD)
    res = client.post("/feedback", json={**GOOD, "message": GOOD["message"].upper() + "  "})
    assert res.status_code == 200
    assert len(stored()) == 1
    assert len(sent) == 1


# ----- Caps -----------------------------------------------------------------

def test_per_ip_limit(client):
    for i in range(3):
        res = client.post("/feedback", json={**GOOD, "message": f"Message number {i}"})
        assert res.status_code == 200
    res = client.post("/feedback", json={**GOOD, "message": "Message number 4"})
    assert res.status_code == 429
    assert "Retry-After" in res.headers
    assert len(stored()) == 3


def test_global_daily_cap(client):
    with TestingSessionLocal() as db:
        for i in range(feedback_module.GLOBAL_DAILY_CAP):
            db.add(Feedback(message=f"earlier message {i}"))
        db.commit()
    res = client.post("/feedback", json=GOOD)
    assert res.status_code == 429
    assert len(stored()) == feedback_module.GLOBAL_DAILY_CAP


def test_global_cap_only_counts_the_last_day(client):
    with TestingSessionLocal() as db:
        for i in range(feedback_module.GLOBAL_DAILY_CAP):
            db.add(Feedback(message=f"old message {i}",
                            created_at=utcnow() - timedelta(days=2)))
        db.commit()
    assert client.post("/feedback", json=GOOD).status_code == 200


# ----- Admin inbox -----------------------------------------------------------

def test_admin_feedback_hidden_from_non_admins(client, auth_headers):
    assert client.get("/admin/feedback").status_code == 401
    assert client.get("/admin/feedback", headers=auth_headers).status_code == 404
    assert client.delete("/admin/feedback/1", headers=auth_headers).status_code == 404


def test_admin_lists_and_deletes_feedback(client, auth_headers, monkeypatch):
    monkeypatch.setattr(admin_access, "_ADMIN_EMAILS", {"ash@example.com"})
    client.post("/feedback", json={**GOOD, "message": "First message here", "page": "/"})
    client.post("/feedback", json={**GOOD, "message": "Second message here",
                                   "email": "misty@example.com"})

    rows = client.get("/admin/feedback", headers=auth_headers).json()
    assert [r["message"] for r in rows] == ["Second message here", "First message here"]
    assert rows[0]["email"] == "misty@example.com"
    assert rows[1]["page"] == "/"

    res = client.delete(f"/admin/feedback/{rows[0]['id']}", headers=auth_headers)
    assert res.status_code == 200
    remaining = client.get("/admin/feedback", headers=auth_headers).json()
    assert [r["message"] for r in remaining] == ["First message here"]
    assert client.delete(f"/admin/feedback/{rows[0]['id']}",
                         headers=auth_headers).status_code == 404
