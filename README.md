# Mintly

A Pokemon TCG portfolio tracker. Search cards, monitor live market prices, and track your collection's value over time.

## Stack

- **Backend** — FastAPI, PostgreSQL, SQLAlchemy, JWT auth
- **Frontend** — React, TypeScript, Vite, React Router

## Features

- Search cards by name, set, or card number
- Live prices pulled from TCGPlayer via the Pokemon TCG API
- Portfolio tracking with gain/loss per card
- User accounts with JWT authentication
- Backend response cache (6-hour TTL) for fast repeated searches
- Debounced search-as-you-type on the frontend

## Getting Started

### Backend

1. Install dependencies:
   ```bash
   cd Backend
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. Create a `.env` file:
   ```
   DATABASE_URL=postgresql://username@localhost:5432/mintly
   SECRET_KEY=your-secret-key
   POKEMON_TCG_API_KEY=your-api-key
   ```

3. Create the database:
   ```bash
   psql postgres -c "CREATE DATABASE mintly;"
   ```

4. Start the server:
   ```bash
   uvicorn card_api:app --reload
   ```

   API runs at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Frontend

1. Install dependencies:
   ```bash
   cd Frontend/mintly
   npm install
   ```

2. Start the dev server:
   ```bash
   npm run dev
   ```

   App runs at `http://localhost:5173`.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register` | Create account |
| POST | `/auth/login` | Login, returns JWT |
| GET | `/search?q=` | Natural language card search |
| GET | `/cards?name=&set_id=&number=` | Filtered card search |
| GET | `/cards/{card_id}` | Get a single card |
| GET | `/sets` | List all sets |
| GET | `/sets/{set_id}/cards` | Cards in a set |
| GET | `/portfolio` | Get your portfolio (auth required) |
| POST | `/portfolio/add` | Add card to portfolio (auth required) |
| DELETE | `/portfolio/{id}` | Remove card from portfolio (auth required) |
