import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Must be set before app modules are imported: database.py builds its engine and
# auth.py reads SECRET_KEY at import time. load_dotenv never overrides existing
# env vars, so these also keep tests off the real Postgres on dev machines.
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("POKEMON_TCG_API_KEY", "test-api-key")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from card_api import app
from database import get_db
from models import Base
import portfolio as portfolio_module

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # one shared in-memory DB across sessions
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


# ---- Fake upstream Pokemon TCG API ----------------------------------------
# portfolio.py talks to the real API via its module-level `_session`; tests
# swap it for this fake so they are fast, deterministic, and offline.

def make_card(card_id: str, name: str = "Test Card", price: float | None = 10.0,
              image: str | None = None) -> dict:
    card = {
        "id": card_id,
        "name": name,
        "images": {"small": image or f"https://img.example/{card_id}/small",
                   "large": image or f"https://img.example/{card_id}/large"},
    }
    if price is not None:
        # real upstream cards carry both; market is what extract_price prefers
        card["tcgplayer"] = {"prices": {"holofoil": {"market": price, "mid": price}}}
    return card


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeUpstream:
    def __init__(self):
        self.cards: dict[str, dict] = {}
        self.calls: list[str] = []

    def add(self, card: dict):
        self.cards[card["id"]] = card

    def get(self, url: str, params: dict | None = None, timeout=None):
        self.calls.append(url)
        if url.endswith("/cards") and params:
            # batched OR-query: q='id:"a" OR id:"b"'
            ids = [part.strip().split(":")[1].strip('"')
                   for part in params["q"].split(" OR ")]
            data = [self.cards[i] for i in ids if i in self.cards]
            return FakeResponse(200, {"data": data})
        card_id = url.rsplit("/", 1)[1]
        if card_id in self.cards:
            return FakeResponse(200, {"data": self.cards[card_id]})
        return FakeResponse(404, {"error": "not found"})


@pytest.fixture(autouse=True)
def upstream(monkeypatch):
    fake = FakeUpstream()
    monkeypatch.setattr(portfolio_module, "_session", fake)
    portfolio_module._price_cache.clear()
    yield fake


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    """Register + log in a default user, return Authorization headers."""
    client.post("/auth/register", json={
        "email": "ash@example.com", "username": "ash", "password": "pikachu1",
        "accepted_terms": True,
    })
    res = client.post("/auth/login", data={"username": "ash", "password": "pikachu1"})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def second_auth_headers(client):
    client.post("/auth/register", json={
        "email": "gary@example.com", "username": "gary", "password": "eevee123",
        "accepted_terms": True,
    })
    res = client.post("/auth/login", data={"username": "gary", "password": "eevee123"})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}
