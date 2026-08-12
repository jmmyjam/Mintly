"""Camera-scanner endpoint tests — offline.

The CLIP model is never loaded: `card_embed.embed_query` is monkeypatched to
return known vectors (like the other tests fake their upstream), so these run
fast without torch. They exercise the endpoint plumbing: nearest-neighbour
ranking over seeded embeddings, empty-catalog handling, and bad input.
"""
import numpy as np
import pytest
from conftest import TestingSessionLocal

from app.models import CatalogCard, ScanFeedback
from app.services import card_catalog, card_embed


@pytest.fixture(autouse=True)
def _reset_embed_cache():
    # The catalog matrix is cached process-wide; clear it so each test's freshly
    # seeded rows are the ones searched.
    card_embed.reset_cache()
    yield
    card_embed.reset_cache()


def catalog_card(card_id: str, name: str) -> dict:
    set_id, number = card_id.split("-")
    return {
        "id": card_id,
        "name": name,
        "number": number,
        "set": {"id": set_id, "name": "Test Set", "releaseDate": "2024/01/01"},
        "images": {"small": f"https://img.example/{card_id}/s",
                   "large": f"https://img.example/{card_id}/l"},
        "tcgplayer": {"prices": {"holofoil": {"market": 5.0}}},
    }


def _unit_vec(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(card_embed.EMBED_DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _seed(pairs: list[tuple[dict, np.ndarray]]) -> None:
    db = TestingSessionLocal()
    try:
        card_catalog.upsert_cards(db, [c for c, _ in pairs])
        for card, vec in pairs:
            db.get(CatalogCard, card["id"]).embedding = np.asarray(vec, np.float32).tobytes()
        db.commit()
    finally:
        db.close()
    card_embed.reset_cache()


def _post(client, headers, content=b"\xff\xd8fakejpeg"):
    return client.post(
        "/scan", files={"file": ("card.jpg", content, "image/jpeg")}, headers=headers
    )


def test_scan_requires_login(client):
    # /scan is login-only — an anonymous request must be rejected before any
    # (compute-heavy) embedding runs.
    res = client.post("/scan", files={"file": ("card.jpg", b"\xff\xd8fake", "image/jpeg")})
    assert res.status_code == 401


def test_scan_returns_nearest_card(client, auth_headers, monkeypatch):
    va, vb = _unit_vec(1), _unit_vec(2)
    _seed([(catalog_card("base1-4", "Charizard"), va),
           (catalog_card("base1-58", "Pikachu"), vb)])
    # query embedding equals Charizard's vector -> it must rank first
    monkeypatch.setattr(card_embed, "embed_query", lambda data: [va])

    res = _post(client, auth_headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data and data[0]["id"] == "base1-4"
    assert data[0]["name"] == "Charizard"
    assert res.json()["totalCount"] == 2


def test_scan_mirror_orientation_still_matches(client, auth_headers, monkeypatch):
    va, vb = _unit_vec(1), _unit_vec(2)
    _seed([(catalog_card("base1-4", "Charizard"), va),
           (catalog_card("base1-58", "Pikachu"), vb)])
    # a "mirror" that only the second orientation matches Charizard -> best-of wins
    monkeypatch.setattr(card_embed, "embed_query", lambda data: [_unit_vec(99), va])

    res = _post(client, auth_headers)
    assert res.status_code == 200
    assert res.json()["data"][0]["id"] == "base1-4"


def test_scan_no_embeddings_is_empty_not_error(client, auth_headers, monkeypatch):
    db = TestingSessionLocal()
    try:
        card_catalog.upsert_cards(db, [catalog_card("base1-4", "Charizard")])
        db.commit()
    finally:
        db.close()
    card_embed.reset_cache()
    monkeypatch.setattr(card_embed, "embed_query", lambda data: [_unit_vec(1)])

    res = _post(client, auth_headers)
    assert res.status_code == 200
    assert res.json()["data"] == []


def test_scan_unreadable_image(client, auth_headers, monkeypatch):
    monkeypatch.setattr(card_embed, "embed_query", lambda data: None)
    res = _post(client, auth_headers, content=b"not-an-image")
    assert res.status_code == 400


def test_scan_empty_upload(client, auth_headers):
    res = _post(client, auth_headers, content=b"")
    assert res.status_code == 400


# ---- Scan accuracy telemetry (POST /scan/feedback) ------------------------

def test_scan_feedback_requires_login(client):
    # Shares the scan router's login gate — an anonymous post is rejected.
    res = client.post("/scan/feedback", json={
        "events": [{"outcome": "confirmed", "candidate_count": 12}],
    })
    assert res.status_code == 401


def test_scan_feedback_records_a_confirmation(client, auth_headers):
    res = client.post("/scan/feedback", json={"events": [{
        "outcome": "confirmed",
        "candidate_count": 12,
        "picked_rank": 0,
        "picked_score": 0.91,
        "top_score": 0.91,
        "top_card_id": "base1-4",
        "picked_card_id": "base1-4",
    }]}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"recorded": 1}

    db = TestingSessionLocal()
    try:
        rows = db.query(ScanFeedback).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.outcome == "confirmed"
        assert row.picked_rank == 0
        assert row.picked_score == 0.91
        assert row.picked_card_id == "base1-4"
        # Deliberately anonymous — there's no user linkage on the row at all.
        assert not hasattr(row, "user_id")
    finally:
        db.close()


def test_scan_feedback_records_a_batch_of_events(client, auth_headers):
    # A batch commit reports one event per queued card in a single call; a pick
    # at rank > 0 means the top guess was wrong and the truth ranked lower.
    res = client.post("/scan/feedback", json={"events": [
        {"outcome": "confirmed", "candidate_count": 12, "picked_rank": 0,
         "picked_score": 0.9, "top_score": 0.9},
        {"outcome": "confirmed", "candidate_count": 12, "picked_rank": 3,
         "picked_score": 0.72, "top_score": 0.81},
    ]}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"recorded": 2}

    db = TestingSessionLocal()
    try:
        ranks = sorted(r.picked_rank for r in db.query(ScanFeedback).all())
        assert ranks == [0, 3]
    finally:
        db.close()


def test_scan_feedback_records_a_miss(client, auth_headers):
    # An explicit "none of these were right" gesture: no pick, so picked_* stay
    # null. These correct the survivorship bias in the confirm-only signal.
    res = client.post("/scan/feedback", json={"events": [{
        "outcome": "searched_away",
        "candidate_count": 12,
        "top_score": 0.44,
        "top_card_id": "base1-58",
    }]}, headers=auth_headers)
    assert res.status_code == 200

    db = TestingSessionLocal()
    try:
        row = db.query(ScanFeedback).one()
        assert row.outcome == "searched_away"
        assert row.picked_rank is None
        assert row.picked_card_id is None
    finally:
        db.close()


def test_scan_feedback_rejects_unknown_outcome(client, auth_headers):
    res = client.post("/scan/feedback", json={"events": [
        {"outcome": "banana", "candidate_count": 12},
    ]}, headers=auth_headers)
    assert res.status_code == 422


def test_scan_feedback_rejects_empty_event_list(client, auth_headers):
    res = client.post("/scan/feedback", json={"events": []}, headers=auth_headers)
    assert res.status_code == 422
