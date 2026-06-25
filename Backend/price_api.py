import os
import requests
import certifi
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.pokemontcg.io/v2"
API_KEY = os.getenv("POKEMON_TCG_API_KEY")

session = requests.Session()
session.verify = certifi.where()
session.headers.update({"X-Api-Key": API_KEY})

app = FastAPI()

# Get all cards
@app.get("/allcards")
def get_allCards():
    response = session.get(f"{BASE_URL}/cards")
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch cards")
    return response.json().get("data", [])

# Search cards by name
@app.get("/cards")
def search_cards(name: str):
    response = session.get(f"{BASE_URL}/cards", params={"q": f"name:{name}"})
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch cards")
    return response.json().get("data", [])

# Get a single card by ID
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
