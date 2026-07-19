from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Index, JSON
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime, timezone

Base = declarative_base()

def utcnow() -> datetime:
    # All DateTime columns store naive UTC; anything comparing against them
    # (e.g. the snapshot daily dedupe) must use this, never local time.
    return datetime.now(timezone.utc).replace(tzinfo=None)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True)
    username = Column(String, unique=True)
    hashed_password = Column(String)
    created_at = Column(DateTime, default=utcnow)
    # When the user accepted the Terms of Service at registration;
    # nullable because accounts created before the requirement have no record
    accepted_terms_at = Column(DateTime, nullable=True)
    portfolio = relationship("PortfolioCard", back_populates="owner")

class PortfolioCard(Base):
    __tablename__ = "portfolio_cards"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    card_id = Column(String)          # e.g. "base1-4" from Pokemon TCG API
    card_name = Column(String)
    quantity = Column(Integer, default=1)
    purchase_price = Column(Float)    # price paid per card
    purchase_date = Column(DateTime, default=utcnow)
    owner = relationship("User", back_populates="portfolio")

class CatalogCard(Base):
    # Local mirror of the upstream card list, so browsing is answered from the
    # DB instead of a 2-5s upstream call. Filled by the daily crawl and topped
    # up whenever the cards router falls back to the upstream proxy.
    __tablename__ = "card_catalog"
    card_id = Column(String, primary_key=True)   # e.g. "base1-4"
    name = Column(String, index=True)
    number = Column(String)
    set_id = Column(String, index=True)
    rarity = Column(String)
    types = Column(String)          # "|Fire|Flying|" — LIKE "%|Fire|%" answers type filters
    release_date = Column(String)   # set releaseDate "YYYY/MM/DD" — sorts as text
    data = Column(JSON)             # the card dict exactly as served to the frontend
    price_updated_at = Column(DateTime, default=utcnow)  # when data's tcgplayer block was last fetched


class CatalogMeta(Base):
    # Catalog bookkeeping (key/value). List endpoints only trust the catalog
    # once a COMPLETE crawl has stamped `last_full_sync` — a partial catalog
    # would confidently serve incomplete search pages.
    __tablename__ = "catalog_meta"
    key = Column(String, primary_key=True)
    value = Column(String)


class CardPriceSnapshot(Base):
    # The app-wide daily price history for ANY card (browsed or held), one row
    # per card per UTC day. Portfolio value-over-time is derived from this by
    # filtering to a user's holdings — there is no separate portfolio table.
    __tablename__ = "card_price_snapshot"
    id = Column(Integer, primary_key=True)
    card_id = Column(String, index=True)
    price = Column(Float)
    snapshot_date = Column(DateTime, default=utcnow)
    # (card_id, date) covers the history + previous-price + portfolio lookups
    __table_args__ = (Index("ix_card_price_snapshot_card_date", "card_id", "snapshot_date"),)
