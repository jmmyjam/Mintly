import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import SessionLocal
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.cards import router as cards_router
from app.routers.health import router as health_router
from app.routers.portfolio import router as portfolio_router
from app.routers.scan import router as scan_router
from app.routers.sitemap import router as sitemap_router
from app.routers.watchlist import router as watchlist_router
from app.services import card_embed

load_dotenv()

# Schema is managed by Alembic — run `alembic upgrade head` after pulling
# model changes (create_all is gone; it could only add tables, never alter).

# Comma-separated list of allowed frontend origins, e.g.
# CORS_ORIGINS=https://mintly.example.com,http://localhost:5173
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Without this the first scan after every restart/deploy pays the ~4s model
    # load. It runs in a background thread, so startup and every other route are
    # never held up by it. SCAN_WARMUP=0 opts out (e.g. a dev `--reload` loop,
    # where each save would otherwise re-import torch).
    if os.getenv("SCAN_WARMUP", "1") != "0":
        card_embed.start_keep_warm(SessionLocal)
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(portfolio_router)
app.include_router(cards_router)
app.include_router(health_router)
app.include_router(sitemap_router)
app.include_router(admin_router)
app.include_router(scan_router)
app.include_router(watchlist_router)
