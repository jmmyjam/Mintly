from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Index, JSON, LargeBinary, UniqueConstraint
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
    # Nullable: an account created via social sign-in (Google/Microsoft) has no
    # password until it sets one through the forgot-password flow. The password
    # login and change-password routes guard against a NULL hash.
    hashed_password = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    # When the user accepted the Terms of Service at registration;
    # nullable because accounts created before the requirement have no record
    accepted_terms_at = Column(DateTime, nullable=True)
    # When the user confirmed control of their email via a verification link
    # (NULL = unverified). Verification is *soft*: an unverified user still uses
    # the app normally — this powers the Profile badge + resend and closes the
    # "reset goes to a typo'd address" gap. Existing accounts were grandfathered
    # verified at migration time. Changing the email (PATCH /me) clears it.
    email_verified_at = Column(DateTime, nullable=True)
    # Bumped to invalidate every outstanding JWT for this user (sign-out-all,
    # password change, password reset). The login token carries this value as
    # its "tv" claim; get_current_user rejects a token whose tv != this. A
    # legacy token minted before this column existed has no tv claim and is read
    # as tv=0 (the default), so it stays valid until the first bump.
    token_version = Column(Integer, nullable=False, default=0, server_default="0")
    portfolio = relationship("PortfolioCard", back_populates="owner")
    portfolios = relationship("Portfolio", back_populates="owner")
    oauth_accounts = relationship("OAuthAccount", back_populates="owner")

class OAuthAccount(Base):
    # A social sign-in identity (Google/Microsoft) linked to a Mintly account.
    # One user may link several providers; a single provider identity maps to at
    # most one user (the unique constraint below). Account MERGING keys on the
    # provider-verified email: signing in with Google/Microsoft whose verified
    # email matches an existing account links to that account instead of making a
    # duplicate (see resolve_oauth_user in routers/auth.py). Cleared on account
    # deletion (no FK cascade). `email` is the address at link time, kept only
    # for reference — the live email lives on the User row.
    __tablename__ = "oauth_accounts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    provider = Column(String, nullable=False)              # "google" | "microsoft"
    provider_account_id = Column(String, nullable=False)   # the OIDC subject ("sub")
    email = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    owner = relationship("User", back_populates="oauth_accounts")
    # One identity per provider maps to one Mintly account; the composite index
    # also serves the returning-user lookup by (provider, sub)
    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id",
                         name="uq_oauth_provider_account"),
    )

class PasswordResetToken(Base):
    # A pending "forgot password" link. Only the sha256 of the emailed token is
    # stored — a DB leak must not hand out working reset links. One live row per
    # user (a new request deletes the old ones); a consumed row keeps used_at so
    # the link can't be replayed. Cleared on account deletion (no FK cascade).
    __tablename__ = "password_reset_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    token_hash = Column(String, unique=True)
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime)
    used_at = Column(DateTime, nullable=True)

class EmailVerificationToken(Base):
    # A pending email-verification link — same shape and handling as
    # PasswordResetToken: only the sha256 of the emailed token is stored (a DB
    # leak must not yield working links), single-use (used_at set on consume),
    # one live row per user (a new send supersedes the old one). Cleared on
    # account deletion (no FK cascade). Longer-lived than reset links (24h) —
    # verification isn't as time-sensitive.
    __tablename__ = "email_verification_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    token_hash = Column(String, unique=True)
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime)
    used_at = Column(DateTime, nullable=True)


class Portfolio(Base):
    # A user's named collection. One user has one or more; the auto-created
    # "My Portfolio" (is_default=True) is the fallback so every user always has
    # at least one to hold cards in — the last portfolio can't be deleted.
    # Cards belong to exactly one portfolio (PortfolioCard.portfolio_id); the
    # price/snapshot pipeline is card_id-keyed and portfolio-agnostic.
    __tablename__ = "portfolios"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String)
    is_default = Column(Boolean, nullable=False, default=False, server_default="0")
    created_at = Column(DateTime, default=utcnow)
    owner = relationship("User", back_populates="portfolios")
    cards = relationship("PortfolioCard", back_populates="portfolio")


class PortfolioCard(Base):
    __tablename__ = "portfolio_cards"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)  # every portfolio query filters on it
    # Which named portfolio this lot lives in. NOT NULL — a lot always has a home
    # (the add flow resolves the target portfolio, defaulting to the user's default).
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), index=True, nullable=False)
    card_id = Column(String)          # e.g. "base1-4" from Pokemon TCG API
    card_name = Column(String)
    quantity = Column(Integer, default=1)
    purchase_price = Column(Float)    # price paid per card
    purchase_date = Column(DateTime, default=utcnow)
    owner = relationship("User", back_populates="portfolio")
    portfolio = relationship("Portfolio", back_populates="cards")

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
    # A CLIP image embedding of the card's artwork (float32 vector, raw bytes),
    # backing the camera scanner's nearest-neighbour match. NULL until the
    # `scripts/embed_catalog.py` backfill fills it; upsert_cards never sets this
    # column, so a written embedding survives the daily crawl untouched.
    embedding = Column(LargeBinary, nullable=True)


class CatalogMeta(Base):
    # Catalog bookkeeping (key/value). List endpoints only trust the catalog
    # once a COMPLETE crawl has stamped `last_full_sync` — a partial catalog
    # would confidently serve incomplete search pages.
    __tablename__ = "catalog_meta"
    key = Column(String, primary_key=True)
    value = Column(String)


class ScanFeedback(Base):
    # Anonymous accuracy telemetry for the camera scanner (roadmap #10:
    # "measure first, then decide"). One row per confirmed pick or explicit
    # miss: when the user adds a scanned card we record which candidate they
    # chose (its rank + CLIP score) and the top candidate's score, so top-K hit
    # rate and the right-vs-wrong score distribution (which calibrates the
    # frontend's shaky-match floor) fall straight out of a GROUP BY. Deliberately
    # NOT linked to a user — it's aggregate measurement, not per-account data, so
    # it stores no personal info and account deletion has nothing to clear. The
    # photo is never stored (see Privacy.tsx §4); only these numbers are. The two
    # card ids let us spot *which* cards get confused (the lookalike-reprint case
    # that would justify collector-number re-ranking).
    __tablename__ = "scan_feedback"
    id = Column(Integer, primary_key=True)
    # "confirmed" (user added this pick), "searched_away" (gave up and searched
    # by name — the top-12 missed), or "rescanned" (rejected the match in batch).
    outcome = Column(String, nullable=False)
    picked_rank = Column(Integer, nullable=True)   # 0 = top guess; NULL for a miss (no pick)
    picked_score = Column(Float, nullable=True)    # CLIP cosine of the chosen card
    top_score = Column(Float, nullable=True)       # CLIP cosine of the rank-0 card
    candidate_count = Column(Integer, nullable=False)
    top_card_id = Column(String, nullable=True)    # rank-0 card id (for confusion analysis)
    picked_card_id = Column(String, nullable=True) # chosen card id (NULL for a miss)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class CardPriceSnapshot(Base):
    # The app-wide daily price history for ANY card (browsed or held), one row
    # per card per variant per UTC day. variant "" is the headline series (the
    # preferred-variant price extract_price picks — what every existing feature
    # reads); named variants ("holofoil", "reverseHolofoil", …) are recorded
    # alongside it for cards with 2+ priced variants, so per-variant history
    # charts work too. Portfolio value-over-time is derived from the headline
    # rows by filtering to a user's holdings — there is no separate portfolio
    # table.
    __tablename__ = "card_price_snapshot"
    id = Column(Integer, primary_key=True)
    card_id = Column(String, index=True)
    variant = Column(String, nullable=False, default="", server_default="")
    price = Column(Float)
    snapshot_date = Column(DateTime, default=utcnow)
    # (card_id, date) covers the history + previous-price + portfolio lookups;
    # the few variant rows per card/day are filtered from the indexed matches
    __table_args__ = (Index("ix_card_price_snapshot_card_date", "card_id", "snapshot_date"),)
