import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.auth import router as auth_router
from app.routers.cards import router as cards_router
from app.routers.portfolio import router as portfolio_router

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
app.include_router(cards_router)
