from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True)
    username = Column(String, unique=True)
    hashed_password = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    portfolio = relationship("PortfolioCard", back_populates="owner")

class PortfolioCard(Base):
    __tablename__ = "portfolio_cards"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    card_id = Column(String)          # e.g. "base1-4" from Pokemon TCG API
    card_name = Column(String)
    quantity = Column(Integer, default=1)
    purchase_price = Column(Float)    # price paid per card
    purchase_date = Column(DateTime, default=datetime.utcnow)
    owner = relationship("User", back_populates="portfolio")

class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshot"
    id = Column(Integer, primary_key=True)
    card_id = Column(String, index=True)  # shared across users, one row per card per day
    price = Column(Float)
    snapshot_date = Column(DateTime, default=datetime.utcnow)
