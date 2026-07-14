# CLAUDE.md

Mintly — Pokemon TCG portfolio tracker. FastAPI + PostgreSQL backend, React 19 + TypeScript + Vite frontend. External data from the Pokemon TCG API (pokemontcg.io); prices via TCGPlayer fields in its responses.

Start every chat message to the user with their name, Jimmy.

Full architecture, endpoint reference, and known behaviors: @HANDOFF.md

## Commands

Backend (run from `Backend/`, uses `venv/`):
```bash
venv/bin/uvicorn card_api:app --reload   # dev server on :8000, docs at /docs
venv/bin/python -m py_compile <file>.py  # quick syntax check
venv/bin/alembic upgrade head            # apply DB migrations
venv/bin/alembic revision --autogenerate -m "..."  # new migration after model changes
venv/bin/pytest tests/ -q                # run backend tests (offline: sqlite + fake upstream)
```

Frontend (run from `Frontend/mintly/` — NOT the repo root):
```bash
npm run dev        # Vite dev server on :5173
npm run build      # tsc + vite build — use this to verify changes compile
npx eslint src/    # lint
```

Backend tests live in `Backend/tests/` (auth, portfolio + card-search routers). `conftest.py` swaps the DB for in-memory SQLite and replaces `portfolio._session` with a fake upstream (`test_search.py` does the same for `card_api.session`) — set env vars / fakes BEFORE importing app modules (they read config at import time). The frontend has no tests yet.

## Structure

- `Backend/card_api.py` — app entry, CORS, card/set proxy endpoints, smart search, in-memory cache (`_cache`, 6h TTL, covers searches + single cards, keyed per query+page; `/sets/{id}` is answered from the cached sets list). Upstream calls take `timeout=_TIMEOUT` (5s connect/60s read — keep it on any new call); the sets cache is served stale if a refresh fails.
- `Backend/auth.py` — register/login, JWT, `get_current_user` dependency, password rules
- `Backend/portfolio.py` — portfolio CRUD, batched price fetching (`fetch_prices`, one upstream call per 100 cards, 15-min `_price_cache`; card image URLs ride along — never guess them from card ids, see HANDOFF), daily snapshots, history endpoint
- `Backend/models.py` — SQLAlchemy models; schema is managed by Alembic (`alembic/versions/`), NOT `create_all` — model changes need a migration
- `Frontend/mintly/src/api.ts` — ALL fetch calls live here; pages never call `fetch` directly
- `Frontend/mintly/src/pages/` — Search, CardDetail, Portfolio, Login, Home, Terms, Privacy (legal pages linked from the Footer)
- `Frontend/mintly/src/components/` — shared UI: Navbar, Footer (brand, links, Pokemon/TCGplayer trademark disclaimer, © line — rendered on every page, on the frame below the panel), HeroSearch (home hero search pill, typewriter placeholder, navigates to `/search?q=`), PriceQtyForm (price+qty add/edit form), StatRow (label/value line), GainLoss (signed colored amount), PageMessage (centered page state), StatusMessage (add success/error line). Reuse these instead of re-inlining their markup in pages.
- `Frontend/mintly/src/hooks.ts` — `useAddCard` (full add-to-portfolio flow: token check, parsing, timed status) and `useSessionRedirect` (the 401 → `/login` redirect + notice). `format.ts` — `money()` dollar formatting.
- `Frontend/mintly/src/App.css` — single stylesheet; use the CSS variables from `index.css` (`--bg-card`, `--border`, `--text`, `--text-h`, `--accent`, `--positive`, `--negative`, `--ink`). Theme is dark/minimal with a framed layout: a neutral near-black outer frame (`--frame`) that the translucent navbar merges into (favicon leaf logo + screen-centered nav pill), with all page content on one big rounded graphite panel (`.main`, `--bg`); cream (`--cream`) primary buttons with ink text, mint accent — keep new UI inside this palette.

## Conventions & invariants

- One `portfolio_cards` row = one purchase (a "lot"). Same card bought twice = two rows; the Portfolio page groups them by `card_id`. Do NOT merge rows or average prices on add.
- Credentials/secrets never go in query strings (they end up in server logs). Register uses a JSON body; keep it that way.
- Price-variant preference order (keep backend `extract_price` and frontend `getCardPrice` in sync): holofoil → normal → reverseHolofoil → 1stEditionHolofoil, using `mid`.
- TCG API query syntax: multi-word `name:` filters MUST be quoted (`name:"pikachu vmax"`) — bare words after a filter return HTTP 400 upstream.
- New React components go in `Frontend/mintly/src/components/`, one file per component — don't define reusable components inline in page files. Pages under `src/pages/` are route entries only; if a piece of UI is (or is about to be) used by more than one page, extract it to `components/` first.
- Authenticated frontend calls go through `authedFetch` in `api.ts` (clears token + throws `SessionExpiredError` on 401). Pages catch that error and redirect to `/login` with a notice in router state — new authed flows must do the same, via `useSessionRedirect` from `hooks.ts` (don't hand-roll the redirect/notice).
- Card searches request only the fields the frontend uses (`_CARD_FIELDS` in `card_api.py`, via the upstream `select=` param). If the frontend `Card` type grows a field, add it there too or it will arrive undefined.
- Card-list endpoints (`/search`, `/cards`, `/sets/{id}/cards`) take `?page=` and return a paged envelope `{data, page, pageSize, totalCount}` (250/page — the upstream max), typed as `CardPage` in `api.ts`. Don't return bare card arrays from new list endpoints.
- Backend validation uses Pydantic models with `Field` constraints (price ≥ 0, quantity ≥ 1); mirror user-facing rules client-side for instant feedback, with identical messages.
- Backend datetimes are naive UTC: use `utcnow()` from `models.py` for anything stored in or compared against a `DateTime` column (snapshot dedupe is per UTC day) — never `datetime.utcnow()` (deprecated) or local `date.today()`.
- Legal pages track reality: any change affecting what user data is stored, auth/session behavior, third-party data flows, or how prices are sourced/shown must update `Terms.tsx`/`Privacy.tsx` (and their "Last updated" dates) in the same change.

## Gotchas

- eslint react-hooks v7 is strict: no synchronous `setState` inside `useEffect` bodies — set state in promise callbacks, or defer via `setTimeout` (see the debounce effect in `Search.tsx`).
- The backend caches (search/card `_cache` and portfolio `_price_cache`) are per-process and in-memory; every `--reload` restart clears them, so the first external-API call after a backend edit is slow. A never-cached search can take the upstream API tens of seconds — that latency is upstream, not a bug.
- The newest card sets (2026 "Mega Evolution" era) have NO price data upstream — empty `tcgplayer.prices` is expected there, and the UI already handles it.
- `Backend/.env` holds real secrets (DB URL, SECRET_KEY, API key) and is gitignored — don't read it into command output or commit it.
- Schema changes: edit `models.py`, then `alembic revision --autogenerate -m "..."`, review the generated file, and `alembic upgrade head`. The app no longer calls `create_all`, so an unapplied migration means missing tables/columns at runtime.
- Always verify with `npm run build` (not just eslint) — the strict tsconfig catches things lint doesn't, e.g. recharts callback param types.
