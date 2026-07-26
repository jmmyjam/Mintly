"""Camera-scanner endpoint tests — offline.

The CLIP model is never loaded: `card_embed.embed_query` is monkeypatched to
return known vectors (like the other tests fake their upstream), so these run
fast without torch. They exercise the endpoint plumbing: nearest-neighbour
ranking over seeded embeddings, empty-catalog handling, and bad input.
"""
import numpy as np
import pytest
from conftest import TestingSessionLocal

from app.models import CatalogCard
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


def _post(client, content=b"\xff\xd8fakejpeg"):
    return client.post("/scan", files={"file": ("card.jpg", content, "image/jpeg")})


def test_scan_returns_nearest_card(client, monkeypatch):
    va, vb = _unit_vec(1), _unit_vec(2)
    _seed([(catalog_card("base1-4", "Charizard"), va),
           (catalog_card("base1-58", "Pikachu"), vb)])
    # query embedding equals Charizard's vector -> it must rank first
    monkeypatch.setattr(card_embed, "embed_query", lambda data: [va])

    res = _post(client)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data and data[0]["id"] == "base1-4"
    assert data[0]["name"] == "Charizard"
    assert res.json()["totalCount"] == 2


def test_scan_mirror_orientation_still_matches(client, monkeypatch):
    va, vb = _unit_vec(1), _unit_vec(2)
    _seed([(catalog_card("base1-4", "Charizard"), va),
           (catalog_card("base1-58", "Pikachu"), vb)])
    # a "mirror" that only the second orientation matches Charizard -> best-of wins
    monkeypatch.setattr(card_embed, "embed_query", lambda data: [_unit_vec(99), va])

    res = _post(client)
    assert res.status_code == 200
    assert res.json()["data"][0]["id"] == "base1-4"


def test_scan_no_embeddings_is_empty_not_error(client, monkeypatch):
    db = TestingSessionLocal()
    try:
        card_catalog.upsert_cards(db, [catalog_card("base1-4", "Charizard")])
        db.commit()
    finally:
        db.close()
    card_embed.reset_cache()
    monkeypatch.setattr(card_embed, "embed_query", lambda data: [_unit_vec(1)])

    res = _post(client)
    assert res.status_code == 200
    assert res.json()["data"] == []


def test_scan_unreadable_image(client, monkeypatch):
    monkeypatch.setattr(card_embed, "embed_query", lambda data: None)
    res = _post(client, content=b"not-an-image")
    assert res.status_code == 400


def test_scan_empty_upload(client):
    res = _post(client, content=b"")
    assert res.status_code == 400
