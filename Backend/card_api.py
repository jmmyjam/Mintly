import os
import re
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
    parts = q.strip().split()
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

    filters = []
    if name_parts:
        filters.append(f"name:{' '.join(name_parts)}")
    if number:
        filters.append(f"number:{number}")
    if set_id:
        filters.append(f"set.id:{set_id}")

    if not filters:
        raise HTTPException(status_code=400, detail="Invalid search query")

    response = session.get(f"{BASE_URL}/cards", params={"q": " ".join(filters)})
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch cards")
    return response.json().get("data", [])


# Search cards — supports name, set code, card number, rarity, and type
# Examples:
#   /cards?name=charizard
#   /cards?name=charizard&set_id=base1
#   /cards?name=charizard&number=4
#   /cards?set_id=base1&number=4
#   /cards?name=charizard&rarity=Rare Holo
#   /cards?type=Fire
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
        filters.append(f"name:{name}")
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

    response = session.get(f"{BASE_URL}/cards", params={"q": " ".join(filters)})
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch cards")
    return response.json().get("data", [])


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
    response = session.get(f"{BASE_URL}/sets")
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch sets")
    return response.json().get("data", [])


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
    response = session.get(f"{BASE_URL}/cards", params={"q": f"set.id:{set_id}"})
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch cards for set")
    return response.json().get("data", [])
