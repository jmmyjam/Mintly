"""Watchlist CRUD + the daily job's price-alert evaluation.

The router resolves a card's name catalog-first then upstream, and prices the
list through the portfolio's fetch pipeline; both reach the same fake upstream
the portfolio tests use (pointed at the watchlist router's own `_session`
below). The alert logic is exercised directly against a seeded DB.
"""
import pytest

from app.models import User, WatchlistItem
from app.routers import watchlist as watchlist_module
from app.services import mailer, watchlist_alerts
from app.services.price_history import record_snapshots
from conftest import TestingSessionLocal, make_card


@pytest.fixture(autouse=True)
def watchlist_session(monkeypatch, upstream):
    """POST /watchlist resolves a card name through the watchlist router's own
    session — point it at the same fake upstream the portfolio uses, so a card
    added there resolves for both name lookup and list pricing."""
    monkeypatch.setattr(watchlist_module, "_session", upstream)
    return upstream


@pytest.fixture
def sent(monkeypatch):
    """Capture alert emails instead of sending (watchlist_alerts resolves
    mailer.send_email at call time)."""
    messages: list[dict] = []

    def capture(to, subject, body, html=None):
        messages.append({"to": to, "subject": subject, "body": body, "html": html})

    monkeypatch.setattr(mailer, "send_email", capture)
    return messages


def make_user(db, email="trainer@example.com", username="trainer") -> User:
    user = User(email=email, username=username, hashed_password="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ----- Router CRUD ------------------------------------------------------------

class TestWatchlistCrud:
    def test_add_and_list(self, client, auth_headers, watchlist_session):
        watchlist_session.add(make_card("base1-4", "Charizard", 100.0))
        res = client.post("/watchlist",
                          json={"card_id": "base1-4", "target_price": 120,
                                "direction": "below"},
                          headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["message"] == "Added to watchlist"

        rows = client.get("/watchlist", headers=auth_headers).json()
        assert len(rows) == 1
        row = rows[0]
        assert row["card_id"] == "base1-4"
        assert row["card_name"] == "Charizard"
        assert row["target_price"] == 120
        assert row["direction"] == "below"
        assert row["current_price"] == 100.0
        assert row["image_url"]
        assert row["triggered"] is True  # 100 <= 120

    def test_triggered_flag_false_when_not_met(self, client, auth_headers,
                                               watchlist_session):
        watchlist_session.add(make_card("base1-4", "Charizard", 100.0))
        client.post("/watchlist",
                    json={"card_id": "base1-4", "target_price": 80,
                          "direction": "below"},
                    headers=auth_headers)
        row = client.get("/watchlist", headers=auth_headers).json()[0]
        assert row["triggered"] is False  # 100 is not <= 80

    def test_watch_only_no_target(self, client, auth_headers, watchlist_session):
        watchlist_session.add(make_card("base1-4", "Charizard", 100.0))
        client.post("/watchlist", json={"card_id": "base1-4"}, headers=auth_headers)
        row = client.get("/watchlist", headers=auth_headers).json()[0]
        assert row["target_price"] is None
        assert row["triggered"] is False

    def test_add_is_upsert(self, client, auth_headers, watchlist_session):
        watchlist_session.add(make_card("base1-4", "Charizard", 100.0))
        client.post("/watchlist", json={"card_id": "base1-4", "target_price": 90},
                    headers=auth_headers)
        res = client.post("/watchlist",
                          json={"card_id": "base1-4", "target_price": 50,
                                "direction": "above"},
                          headers=auth_headers)
        assert res.json()["message"] == "Watchlist updated"
        rows = client.get("/watchlist", headers=auth_headers).json()
        assert len(rows) == 1  # no duplicate
        assert rows[0]["target_price"] == 50
        assert rows[0]["direction"] == "above"

    def test_update(self, client, auth_headers, watchlist_session):
        watchlist_session.add(make_card("base1-4", "Charizard", 100.0))
        item_id = client.post("/watchlist",
                              json={"card_id": "base1-4", "target_price": 90},
                              headers=auth_headers).json()["id"]
        res = client.patch(f"/watchlist/{item_id}",
                           json={"target_price": 150, "direction": "above"},
                           headers=auth_headers)
        assert res.status_code == 200
        row = client.get("/watchlist", headers=auth_headers).json()[0]
        assert row["target_price"] == 150
        assert row["direction"] == "above"

    def test_delete(self, client, auth_headers, watchlist_session):
        watchlist_session.add(make_card("base1-4", "Charizard", 100.0))
        item_id = client.post("/watchlist", json={"card_id": "base1-4"},
                              headers=auth_headers).json()["id"]
        assert client.delete(f"/watchlist/{item_id}",
                             headers=auth_headers).status_code == 200
        assert client.get("/watchlist", headers=auth_headers).json() == []

    def test_add_unknown_card_404(self, client, auth_headers):
        res = client.post("/watchlist", json={"card_id": "nope-1"},
                          headers=auth_headers)
        assert res.status_code == 404

    def test_negative_target_rejected(self, client, auth_headers, watchlist_session):
        watchlist_session.add(make_card("base1-4", "Charizard", 100.0))
        res = client.post("/watchlist",
                          json={"card_id": "base1-4", "target_price": -5},
                          headers=auth_headers)
        assert res.status_code == 422


class TestWatchlistScoping:
    def test_other_user_cannot_see_or_touch(self, client, auth_headers,
                                            second_auth_headers, watchlist_session):
        watchlist_session.add(make_card("base1-4", "Charizard", 100.0))
        item_id = client.post("/watchlist", json={"card_id": "base1-4"},
                              headers=auth_headers).json()["id"]
        # Second user sees an empty list and can't patch/delete the first's item
        assert client.get("/watchlist", headers=second_auth_headers).json() == []
        assert client.patch(f"/watchlist/{item_id}", json={"target_price": 1},
                            headers=second_auth_headers).status_code == 404
        assert client.delete(f"/watchlist/{item_id}",
                             headers=second_auth_headers).status_code == 404

    def test_requires_auth(self, client):
        assert client.get("/watchlist").status_code == 401
        assert client.post("/watchlist", json={"card_id": "base1-4"}).status_code == 401

    def test_account_deletion_clears_watchlist(self, client, auth_headers,
                                               watchlist_session):
        watchlist_session.add(make_card("base1-4", "Charizard", 100.0))
        client.post("/watchlist", json={"card_id": "base1-4"}, headers=auth_headers)
        assert client.delete("/auth/me", headers=auth_headers).status_code == 200
        db = TestingSessionLocal()
        try:
            assert db.query(WatchlistItem).count() == 0
        finally:
            db.close()


# ----- Alert evaluation (the daily job's watchlist_alerts.evaluate) -----------

class TestAlertEvaluation:
    def _watch(self, db, user, card_id, target, direction="below"):
        item = WatchlistItem(user_id=user.id, card_id=card_id,
                             card_name=card_id, target_price=target,
                             direction=direction)
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def test_below_triggers_and_stamps(self, sent):
        db = TestingSessionLocal()
        try:
            user = make_user(db)
            item = self._watch(db, user, "base1-4", 100.0)
            record_snapshots(db, {"base1-4": 95.0})  # dipped below the target
            run = watchlist_alerts.evaluate(db)
            assert run.alerts_sent == 1
            assert run.users_notified == 1
            assert len(sent) == 1
            assert sent[0]["to"] == user.email
            assert "$95.00" in sent[0]["body"]
            db.refresh(item)
            assert item.last_alerted_at is not None
        finally:
            db.close()

    def test_not_re_alerted_while_still_triggered(self, sent):
        db = TestingSessionLocal()
        try:
            user = make_user(db)
            self._watch(db, user, "base1-4", 100.0)
            record_snapshots(db, {"base1-4": 95.0})
            watchlist_alerts.evaluate(db)
            watchlist_alerts.evaluate(db)  # price still 95 — no second email
            assert len(sent) == 1
        finally:
            db.close()

    def test_re_arm_after_recovery(self, sent):
        db = TestingSessionLocal()
        try:
            user = make_user(db)
            item = self._watch(db, user, "base1-4", 100.0)
            record_snapshots(db, {"base1-4": 95.0})
            watchlist_alerts.evaluate(db)          # alert #1
            record_snapshots(db, {"base1-4": 110.0})  # recovered above target
            run = watchlist_alerts.evaluate(db)    # re-arm, no email
            assert run.rearmed == 1
            db.refresh(item)
            assert item.last_alerted_at is None
            record_snapshots(db, {"base1-4": 90.0})  # dipped again
            watchlist_alerts.evaluate(db)          # alert #2
            assert len(sent) == 2
        finally:
            db.close()

    def test_above_direction(self, sent):
        db = TestingSessionLocal()
        try:
            user = make_user(db)
            self._watch(db, user, "base1-4", 100.0, direction="above")
            record_snapshots(db, {"base1-4": 105.0})  # rose above target
            run = watchlist_alerts.evaluate(db)
            assert run.alerts_sent == 1
            assert "risen above" in sent[0]["body"]
        finally:
            db.close()

    def test_watch_only_never_alerts(self, sent):
        db = TestingSessionLocal()
        try:
            user = make_user(db)
            self._watch(db, user, "base1-4", None)  # no target
            record_snapshots(db, {"base1-4": 1.0})
            run = watchlist_alerts.evaluate(db)
            assert run.alerts_sent == 0
            assert sent == []
        finally:
            db.close()

    def test_one_email_groups_a_users_cards(self, sent):
        db = TestingSessionLocal()
        try:
            user = make_user(db)
            self._watch(db, user, "base1-4", 100.0)
            self._watch(db, user, "base1-5", 50.0)
            record_snapshots(db, {"base1-4": 95.0, "base1-5": 40.0})
            run = watchlist_alerts.evaluate(db)
            assert run.alerts_sent == 2
            assert run.users_notified == 1
            assert len(sent) == 1  # one email, both cards
            assert "2" in sent[0]["subject"]
        finally:
            db.close()

    def test_separate_users_get_separate_emails(self, sent):
        db = TestingSessionLocal()
        try:
            a = make_user(db, "a@example.com", "aaa")
            b = make_user(db, "b@example.com", "bbb")
            self._watch(db, a, "base1-4", 100.0)
            self._watch(db, b, "base1-4", 100.0)
            record_snapshots(db, {"base1-4": 95.0})
            run = watchlist_alerts.evaluate(db)
            assert run.users_notified == 2
            assert {m["to"] for m in sent} == {"a@example.com", "b@example.com"}
        finally:
            db.close()

    def test_card_without_snapshot_is_skipped(self, sent):
        db = TestingSessionLocal()
        try:
            user = make_user(db)
            self._watch(db, user, "base1-4", 100.0)  # never priced
            run = watchlist_alerts.evaluate(db)
            assert run.alerts_sent == 0
            assert sent == []
        finally:
            db.close()

    def test_send_failure_leaves_item_unstamped(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("smtp down")
        monkeypatch.setattr(mailer, "send_email", boom)
        db = TestingSessionLocal()
        try:
            user = make_user(db)
            item = self._watch(db, user, "base1-4", 100.0)
            record_snapshots(db, {"base1-4": 95.0})
            run = watchlist_alerts.evaluate(db)
            assert run.failures == 1
            assert run.alerts_sent == 0
            db.refresh(item)
            assert item.last_alerted_at is None  # retried next run
        finally:
            db.close()
