import os
import re
import time
import requests
import certifi
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from auth import router as auth_router
from portfolio import router as portfolio_router

load_dotenv()

# Schema is managed by Alembic — run `alembic upgrade head` after pulling
# model changes (create_all is gone; it could only add tables, never alter).

BASE_URL = "https://api.pokemontcg.io/v2"
API_KEY = os.getenv("POKEMON_TCG_API_KEY")


# Comma-separated list of allowed frontend origins, e.g.
# CORS_ORIGINS=https://mintly.example.com,http://localhost:5173
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(portfolio_router)

session = requests.Session()
session.verify = certifi.where()
session.headers.update({"X-Api-Key": API_KEY})

_cache: dict[str, tuple[float, list | dict]] = {}
_CACHE_TTL = 21600 #6 hours until cache reset

# Only the fields the frontend uses — full card objects (attacks, legalities, etc.)
# are several times larger and slower for the upstream API to serve
_CARD_FIELDS = "id,name,number,rarity,artist,hp,types,images,set,tcgplayer"

_PAGE_SIZE = 250  # upstream maximum


def _fetch_cards(q: str, page: int = 1) -> dict:
    key = f"{q}|page:{page}"
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
    response = session.get(
        f"{BASE_URL}/cards",
        params={"q": q, "select": _CARD_FIELDS, "page": page, "pageSize": _PAGE_SIZE},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch cards")
    payload = response.json()
    cards = payload.get("data", [])
    data = {
        "data": cards,
        "page": page,
        "pageSize": payload.get("pageSize", _PAGE_SIZE),
        "totalCount": payload.get("totalCount", len(cards)),
    }
    _cache[key] = (time.time(), data)
    return data


def _fetch_card(card_id: str) -> dict:
    key = f"__card__{card_id}"
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
    response = session.get(f"{BASE_URL}/cards/{card_id}")
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Card not found")
    data = response.json().get("data", {})
    _cache[key] = (time.time(), data)
    return data


def _fetch_sets() -> list:
    if "__sets__" in _cache:
        ts, data = _cache["__sets__"]
        if time.time() - ts < _CACHE_TTL:
            return data
    response = session.get(f"{BASE_URL}/sets")
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch sets")
    data = response.json().get("data", [])
    _cache["__sets__"] = (time.time(), data)
    return data


# Natural language search
@app.get("/search")
def smart_search(q: str, page: int = Query(1, ge=1)):
    parts = q.strip().replace('"', "").split()
    number = None
    set_id = None
    name_parts = []

    for part in parts:
        if re.fullmatch(r'\d+', part):
            number = part
        elif re.fullmatch(r'[a-zA-Z]+\d+', part):
            set_id = part
        else:
            name_parts.append(part)

    # Recognize set names in the query, e.g. "pikachu lost origin" (longest match wins)
    if set_id is None and name_parts:
        set_names = {s["name"].lower(): s["id"] for s in _fetch_sets()}
        n = len(name_parts)
        for size in range(n, 0, -1):
            match = None
            for start in range(n - size + 1):
                candidate = " ".join(name_parts[start:start + size]).lower()
                if candidate in set_names:
                    match = (start, size, set_names[candidate])
                    break
            if match:
                start, size, set_id = match
                name_parts = name_parts[:start] + name_parts[start + size:]
                break

    def build_query(name_words: list[str]) -> str:
        filters = []
        if name_words:
            filters.append(f'name:"{" ".join(name_words)}"')
        if number:
            filters.append(f"number:{number}")
        if set_id:
            filters.append(f"set.id:{set_id}")
        return " ".join(filters)

    if not name_parts and not number and not set_id:
        raise HTTPException(status_code=400, detail="Invalid search query")

    results = _fetch_cards(build_query(name_parts), page)

    # Fallback for loose names like "sleepy pikachu": drop words until something matches.
    # Keyed on totalCount, not the page's data — an empty page 2 of a real query
    # must not trigger the fallback.
    if results["totalCount"] == 0 and len(name_parts) > 1:
        for i in range(1, len(name_parts)):
            for candidate in (name_parts[i:], name_parts[:-i]):
                results = _fetch_cards(build_query(candidate), page)
                if results["totalCount"] > 0:
                    return results
    return results


# Search cards — supports name, set code, card number, rarity, and type
@app.get("/cards")
def search_cards(
    name: str | None = None,
    set_id: str | None = None,
    number: str | None = None,
    rarity: str | None = None,
    type: str | None = None,
    page: int = Query(1, ge=1),
):
    filters = []
    if name:
        filters.append(f'name:"{name.replace(chr(34), "")}"')
    if set_id:
        filters.append(f"set.id:{set_id}")
    if number:
        filters.append(f"number:{number}")
    if rarity:
        filters.append(f'rarity:"{rarity}"')
    if type:
        filters.append(f"types:{type}")

    if not filters:
        raise HTTPException(status_code=400, detail="Provide at least one search parameter")

    return _fetch_cards(" ".join(filters), page)


# Get a single card by its API ID (e.g. base1-4)
@app.get("/cards/{card_id}")
def get_card(card_id: str):
    return _fetch_card(card_id)


# List all sets
@app.get("/sets")
def get_sets():
    return _fetch_sets()


# Get a single set by its ID (e.g. base1, swsh1)
@app.get("/sets/{set_id}")
def get_set(set_id: str):
    # The cached sets list already has every set — no upstream call needed
    for s in _fetch_sets():
        if s.get("id") == set_id:
            return s
    raise HTTPException(status_code=404, detail="Set not found")


# Get all cards in a set
@app.get("/sets/{set_id}/cards")
def get_set_cards(set_id: str, page: int = Query(1, ge=1)):
    return _fetch_cards(f"set.id:{set_id}", page)
