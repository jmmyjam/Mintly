# CLAUDE.md

Mintly — Pokemon TCG portfolio tracker. FastAPI + PostgreSQL backend, React 19 + TypeScript + Vite frontend. External data from the Pokemon TCG API (pokemontcg.io); prices via TCGPlayer fields in its responses.

Full architecture, endpoint reference, and known behaviors: @HANDOFF.md

## Commands

Backend (run from `Backend/`, uses `venv/`):
```bash
venv/bin/uvicorn card_api:app --reload   # dev server on :8000, docs at /docs
venv/bin/python -m py_compile <file>.py  # quick syntax check
```

Frontend (run from `Frontend/mintly/` — NOT the repo root):
```bash
npm run dev        # Vite dev server on :5173
npm run build      # tsc + vite build — use this to verify changes compile
npx eslint src/    # lint
```

There are no tests yet.

## Structure

- `Backend/card_api.py` — app entry, CORS, card/set proxy endpoints, smart search, in-memory cache (`_cache`, 6h TTL)
- `Backend/auth.py` — register/login, JWT, `get_current_user` dependency, password rules
- `Backend/portfolio.py` — portfolio CRUD, price fetching, daily snapshots, history endpoint
- `Backend/models.py` — SQLAlchemy models; tables auto-created via `create_all` (Alembic is scaffolded but unused — no migrations exist)
- `Frontend/mintly/src/api.ts` — ALL fetch calls live here; pages never call `fetch` directly
- `Frontend/mintly/src/pages/` — Search, CardDetail, Portfolio, Login, Home
- `Frontend/mintly/src/App.css` — single stylesheet; use the CSS variables from `index.css` (`--bg-card`, `--border`, `--text`, `--text-h`, `--accent`, `--positive`, `--negative`)

## Conventions & invariants

- One `portfolio_cards` row = one purchase (a "lot"). Same card bought twice = two rows; the Portfolio page groups them by `card_id`. Do NOT merge rows or average prices on add.
- Credentials/secrets never go in query strings (they end up in server logs). Register uses a JSON body; keep it that way.
- Price-variant preference order (keep backend `extract_price` and frontend `getCardPrice` in sync): holofoil → normal → reverseHolofoil → 1stEditionHolofoil, using `mid`.
- TCG API query syntax: multi-word `name:` filters MUST be quoted (`name:"pikachu vmax"`) — bare words after a filter return HTTP 400 upstream.
- Authenticated frontend calls go through `authedFetch` in `api.ts` (clears token + throws "Session expired" on 401). New authed endpoints should use it.
- Backend validation uses Pydantic models with `Field` constraints (price ≥ 0, quantity ≥ 1); mirror user-facing rules client-side for instant feedback, with identical messages.

## Gotchas

- eslint react-hooks v7 is strict: no synchronous `setState` inside `useEffect` bodies — set state in promise callbacks, or defer via `setTimeout` (see the debounce effect in `Search.tsx`).
- The backend cache is per-process and in-memory; every `--reload` restart clears it, so the first external-API call after a backend edit is slow (1–3s). Don't mistake that for a bug.
- The newest card sets (2026 "Mega Evolution" era) have NO price data upstream — empty `tcgplayer.prices` is expected there, and the UI already handles it.
- `Backend/.env` holds real secrets (DB URL, SECRET_KEY, API key) and is gitignored — don't read it into command output or commit it.
- `create_all` only creates missing tables; it never alters existing ones. Column changes require manual SQL or finally adopting Alembic.
- Always verify with `npm run build` (not just eslint) — the strict tsconfig catches things lint doesn't, e.g. recharts callback param types.
