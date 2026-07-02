import os
import re
import time
import requests
import certifi
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from database import engine
from models import Base
from auth import router as auth_router
from portfolio import router as portfolio_router

load_dotenv()

Base.metadata.create_all(bind=engine)

BASE_URL = "https://api.pokemontcg.io/v2"
API_KEY = os.getenv("POKEMON_TCG_API_KEY")

session = requests.Session()
session.verify = certifi.where()
session.headers.update({"X-Api-Key": API_KEY})

_cache: dict[str, tuple[float, list]] = {}
_CACHE_TTL = 21600 #6 hours until cache reset

def _fetch_cards(q: str) -> list:
    if q in _cache:
        ts, data = _cache[q]
        if time.time() - ts < _CACHE_TTL:
            return data
    response = session.get(f"{BASE_URL}/cards", params={"q": q})
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch cards")
    data = response.json().get("data", [])
    _cache[q] = (time.time(), data)
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

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(portfolio_router)

# Natural language search
@app.get("/search")
def smart_search(q: str):
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

    results = _fetch_cards(build_query(name_parts))

    # Fallback for loose names like "sleepy pikachu": drop words until something matches
    if not results and len(name_parts) > 1:
        for i in range(1, len(name_parts)):
            for candidate in (name_parts[i:], name_parts[:-i]):
                results = _fetch_cards(build_query(candidate))
                if results:
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

    return _fetch_cards(" ".join(filters))


# Get a single card by its API ID (e.g. base1-4)
@app.get("/cards/{card_id}")
def get_card(card_id: str):
    response = session.get(f"{BASE_URL}/cards/{card_id}")
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Card not found")
    return response.json().get("data", {})


# List all sets
@app.get("/sets")
def get_sets():
    return _fetch_sets()


# Get a single set by its ID (e.g. base1, swsh1)
@app.get("/sets/{set_id}")
def get_set(set_id: str):
    response = session.get(f"{BASE_URL}/sets/{set_id}")
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Set not found")
    return response.json().get("data", {})


# Get all cards in a set
@app.get("/sets/{set_id}/cards")
def get_set_cards(set_id: str):
    return _fetch_cards(f"set.id:{set_id}")
