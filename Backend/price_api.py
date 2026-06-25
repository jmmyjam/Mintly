import ssl
import certifi
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

from fastapi import FastAPI
from pokemontcgsdk import Card, Set, Type, Supertype, Subtype, Rarity

app = FastAPI()

# Get all acrds
@app.get("/allcards")
def get_allCards():
    cards = Card.all()
    return [{"id": c.id, "name": c.name, "set": c.set.name, "prices": c.tcgplayer} for c in cards]

# Search cards by name
@app.get("/cards")
def search_cards(name: str):
    cards = Card.where(q=f"name:{name}")
    return [{"id": c.id, "name": c.name, "set": c.set.name, "prices": c.tcgplayer} for c in cards]

# Get a single card by ID
@app.get("/cards/{card_id}")
def get_card(card_id: str):
    card = Card.find(card_id)
    return {"id": card.id, "name": card.name, "prices": card.tcgplayer}

# List all sets
@app.get("/sets")
def get_sets():
    sets = Set.all()
    return [{"id": s.id, "name": s.name, "total": s.total} for s in sets]