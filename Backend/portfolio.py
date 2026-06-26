from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import requests
import certifi
import os
from dotenv import load_dotenv

from database import get_db
from models import PortfolioCard
from auth import get_current_user

load_dotenv()

BASE_URL = "https://api.pokemontcg.io/v2"
API_KEY = os.getenv("POKEMON_TCG_API_KEY")

_session = requests.Session()
_session.verify = certifi.where()
_session.headers.update({"X-Api-Key": API_KEY})

router = APIRouter()


class AddCardRequest(BaseModel):
    card_id: str
    purchase_price: float
    quantity: int = 1


def fetch_price(card_id: str) -> float | None:
    response = _session.get(f"{BASE_URL}/cards/{card_id}")
    if response.status_code != 200:
        return None
    prices = response.json().get("data", {}).get("tcgplayer", {}).get("prices", {})
    for price_type in ("holofoil", "normal", "reverseHolofoil", "1stEditionHolofoil"):
        mid = prices.get(price_type, {}).get("mid")
        if mid is not None:
            return mid
    return None


@router.post("/portfolio/add")
def add_card(body: AddCardRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    response = _session.get(f"{BASE_URL}/cards/{body.card_id}")
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Card not found")
    card_name = response.json().get("data", {}).get("name", "Unknown")

    card = PortfolioCard(
        user_id=current_user.id,
        card_id=body.card_id,
        card_name=card_name,
        purchase_price=body.purchase_price,
        quantity=body.quantity,
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return {"message": "Card added", "id": card.id}


@router.get("/portfolio")
def get_portfolio(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    cards = db.query(PortfolioCard).filter(PortfolioCard.user_id == current_user.id).all()
    result = []
    for c in cards:
        current_price = fetch_price(c.card_id)
        gain_loss = round((current_price - c.purchase_price) * c.quantity, 2) if current_price is not None else None
        gain_loss_pct = round(((current_price - c.purchase_price) / c.purchase_price) * 100, 2) if current_price and c.purchase_price else None
        result.append({
            "id": c.id,
            "card_id": c.card_id,
            "card_name": c.card_name,
            "quantity": c.quantity,
            "purchase_price": c.purchase_price,
            "purchase_date": c.purchase_date,
            "current_price": current_price,
            "gain_loss": gain_loss,
            "gain_loss_pct": gain_loss_pct,
        })
    return result


@router.delete("/portfolio/{portfolio_card_id}")
def remove_card(portfolio_card_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    card = db.query(PortfolioCard).filter(
        PortfolioCard.id == portfolio_card_id,
        PortfolioCard.user_id == current_user.id,
    ).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found in portfolio")
    db.delete(card)
    db.commit()
    return {"message": "Card removed"}
