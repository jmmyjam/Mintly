# Mintly — Handoff Document

*Last updated: July 13, 2026*

A Pokemon TCG portfolio tracker: search cards, view live market prices, and track a collection's value over time.

## Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI, PostgreSQL, SQLAlchemy, JWT auth (python-jose + passlib/bcrypt) |
| Frontend | React 19, TypeScript, Vite, React Router 7, Recharts |
| Data source | [Pokemon TCG API](https://pokemontcg.io) (prices via TCGPlayer) |

## Running locally

**Backend** (from `Backend/`):
```bash
source venv/bin/activate
alembic upgrade head                 # apply DB migrations (needed on first run / after pulling schema changes)
uvicorn card_api:app --reload        # http://localhost:8000, docs at /docs
pip install -r requirements-dev.txt  # test deps (pytest, httpx)
pytest tests/ -q                     # backend tests — offline (in-memory SQLite + fake upstream API)
```
Requires a `.env` in `Backend/` (not committed):
```
DATABASE_URL=postgresql://username@localhost:5432/mintly
SECRET_KEY=...
POKEMON_TCG_API_KEY=...
CORS_ORIGINS=http://localhost:5173   # optional — comma-separated allowed frontend origins (this is the default)
```

**Frontend** (from `Frontend/mintly/`):
```bash
npm install
npm run dev                          # http://localhost:5173
npm run build                        # type-check + production build
npx eslint src/                      # lint (strict react-hooks rules enabled)
```
The API base URL comes from `VITE_API_BASE` (see `.env.example`; baked in at build time). Unset it for local dev — it defaults to `http://localhost:8000`.

## Architecture

### Backend files
- `card_api.py` — FastAPI app, CORS (origins from `CORS_ORIGINS` env var, comma-separated; defaults to `http://localhost:5173`), card/set proxy endpoints, smart search, in-memory response cache (6-hour TTL, per-process, cleared on every `--reload` restart; covers searches and single-card lookups, keyed per query+page). Card-list endpoints are paginated: they take `?page=` and return an envelope `{data, page, pageSize, totalCount}` (250 cards/page — the upstream max). Card searches pass `select=` upstream (`_CARD_FIELDS`) so responses carry only the fields the frontend uses — a full-set search is ~90KB instead of multiple MB. `/sets/{id}` is answered from the cached sets list with no upstream call.
- `auth.py` — register/login, JWT creation/validation (`get_current_user` dependency), password rules.
- `portfolio.py` — portfolio CRUD, batched price fetching, daily price snapshots, history endpoint. `fetch_prices` resolves all held cards in one upstream OR-query (`id:"a" OR id:"b" …`, chunks of 100) and caches per-card prices for 15 minutes (`_price_cache`); `/portfolio/add` seeds that cache from the card it already fetched.
- `models.py` — SQLAlchemy models.
- `database.py` — engine/session setup from `DATABASE_URL`.
- `tests/` — pytest suite for the auth, portfolio, and card-search routers (38 tests, runs offline in ~9s). `conftest.py` sets `DATABASE_URL`/`SECRET_KEY` env vars **before** importing app modules (they read config at import time), overrides `get_db` with an in-memory SQLite session, and swaps `portfolio._session` for a `FakeUpstream` — no Postgres or network needed. `test_search.py` likewise swaps `card_api.session` for a paged fake. Dev deps: `requirements-dev.txt`.
- Schema is managed by **Alembic** (`alembic/versions/`); `env.py` reads `DATABASE_URL` from `Backend/.env` and targets `models.Base.metadata`, so `alembic revision --autogenerate` works. The app no longer calls `create_all` at startup — after changing `models.py`, generate a migration, review it, and run `alembic upgrade head`. Databases created under the old `create_all` regime were stamped at the initial revision (`alembic stamp head` before the first real migration).

### Data model
- `users` — id, email, username, hashed_password (bcrypt), created_at.
- `portfolio_cards` — one row per **purchase (lot)**: user_id, card_id (TCG API id like `base1-4`), card_name, quantity, purchase_price, purchase_date. The same card bought twice = two rows; the frontend groups them visually.
- `portfolio_snapshot` — one row per card per day: card_id, price, snapshot_date. Shared across users. Written whenever any user loads their portfolio (deduped per day).

### API endpoints
| Endpoint | Notes |
|---|---|
| `POST /auth/register` | JSON body (never query params — passwords would hit logs). Password rules: ≥8 chars, ≥1 letter, ≥1 number. |
| `POST /auth/login` | OAuth2 form body; accepts email **or** username. Returns a 7-day JWT. |
| `GET /search?q=&page=` | Smart search — see below. Returns `{data, page, pageSize, totalCount}` (250/page). |
| `GET /cards?name=&set_id=&number=&rarity=&type=&page=` | Filtered search; drives the frontend filter bar. Same paged envelope. |
| `GET /cards/{card_id}` | Single card; drives the detail page. Cached (6h). |
| `GET /sets`, `GET /sets/{id}`, `GET /sets/{id}/cards?page=` | Sets list is cached; single sets served from it; drives filter dropdown + default view. |
| `GET /portfolio` | Auth. Returns one row per lot with live price, P&L, and the card's real `image_url` (all fetched in one batched upstream call, 15-min cache). Also records today's snapshots as a side effect. |
| `GET /portfolio/history` | Auth. `[{date, total_value}]` from snapshots × current holdings; missing days carry the last known price forward. |
| `POST /portfolio/add` | Auth. `purchase_price` optional → falls back to current market price (400 if the card has none). |
| `PATCH /portfolio/{id}` | Auth. Update `purchase_price` and/or `quantity` on one lot. |
| `DELETE /portfolio/{id}` | Auth. Remove one lot. |

### Smart search (`/search`)
Tokenizes the query, then:
1. Digits → card number; letters+digits (e.g. `swsh11`) → set id; rest → name words.
2. Scans name words for a real **set name** (longest contiguous match against the cached sets list) — "pikachu lost origin" → `name:"pikachu" set.id:swsh11`.
3. Name is always quoted (unquoted multi-word queries are a syntax error upstream → HTTP 400).
4. If nothing matches, retries dropping words from the front, then the back — "sleepy pikachu" falls back to "pikachu". "Nothing matches" means `totalCount == 0`, not an empty page — so requesting a page past the end of a valid query doesn't trigger the fallback.

### Frontend pages (`src/pages/`)
- `Search.tsx` — debounced (400ms) search-as-you-type; filter bar (set/rarity/type/number → `/cards`, otherwise `/search`); shows the newest set by default when empty; "add to portfolio" inline form. Multi-page results get a Prev/Next pager (above and below the grid); any query/filter change resets to page 1, and page moves skip the debounce.
- `CardDetail.tsx` — route `/card/:cardId`; large image, set/rarity/type/HP/artist facts, full price-variant table (low/mid/high/market), add form with market price pre-filled. Linked from search results and portfolio tiles.
- `Portfolio.tsx` — summary stats, value-over-time area chart, card grid grouped by card with expandable per-purchase (lot) breakdown; inline edit per lot. Renders as soon as the portfolio arrives; the history chart fills in when the (deliberately later) history call returns. Client-side toolbar above the grid: name filter, gainers/losers filter, and sort (recently added [default] / highest value / biggest gain / biggest loss / name) — all computed per card *group*; cards without price data sort last and match neither gainers nor losers. Summary stats always reflect the full portfolio, not the filtered view.
- `Login.tsx` — combined login/register with client-side password validation mirroring the backend. Shows a notice (e.g. "Your session expired") when redirected here via router state.
- `api.ts` — all fetch calls. `authedFetch` wraps authenticated requests: any 401 clears the stored token and throws `SessionExpiredError`; pages catch it and redirect to `/login` with that notice (via `useSessionRedirect`). Token lives in `localStorage`.

### Shared frontend modules
- `src/components/` — `Navbar`, plus the pieces the pages share: `PriceQtyForm` (the price+quantity form behind Search's inline add, CardDetail's labeled add, and Portfolio's lot editor — props switch labels, button size, busy state, optional Cancel), `StatRow` (label/value `price-row` line), `GainLoss` (signed, colored dollar amount with optional percent), `PageMessage` (centered full-page loading/error/logged-out state with optional CTA link), `StatusMessage` (success/error line after an add). New page UI that matches one of these should reuse it, not re-inline the markup.
- `src/hooks.ts` — `useAddCard`: the whole add-to-portfolio flow (token check → `/login` redirect, price/qty parsing, self-clearing status message — 3s success / 4s error, busy flag) shared by Search and CardDetail; `useSessionRedirect`: the single source of the "Your session expired — please log in again." redirect — every authed flow must use it so the notice stays in sync with `Login.tsx`.
- `src/format.ts` — `money()`: `$12.34`, or an em dash for missing values.

## Behaviors worth knowing

- **Price picking**: first available `mid` among holofoil → normal → reverseHolofoil → 1stEditionHolofoil (`extract_price` backend, `getCardPrice` frontend — keep in sync).
- **History chart**: computed against *current* holdings, so editing a quantity retroactively changes past points. Snapshots only record on days someone loads their portfolio. With <2 days of data the chart shows a flat placeholder line at today's value.
- **Newest sets have no prices**: the upstream API has zero TCGPlayer data for the 2026 "Mega Evolution" era sets (verified: me4, me3, me2pt5 all 0/N cards). The UI shows a "prices unavailable" note when a whole result set is priceless; blank-price adds for those cards are rejected with a clear message. Not a bug — upstream data lag.
- **Add button** shows "Adding…" and blocks double-clicks (the add round-trips to the external API, 1–3s).
- **Session expiry**: JWTs last 7 days. Any authed call after expiry gets a 401 → token cleared → redirect to `/login` with a "session expired" notice (`SessionExpiredError` in `api.ts`, redirect via `useSessionRedirect` in `hooks.ts`).
- **Upstream latency dominates cold requests**: a never-cached search can take the upstream API tens of seconds; caching + `select=` trimming make repeats fast but can't fix the first hit. Portfolio loads are one batched call regardless of collection size (measured ~0.8s cold, ~4ms warm for 5 cards).
- **Upstream is occasionally flaky, not just slow**: observed (July 10, 2026) `GET /sets` transiently returning 404 and taking ~50s when it did succeed. Because smart search needs the sets list, a cold cache + upstream flake surfaces as `{"detail": "Failed to fetch sets"}` from `/search`; it self-heals on the next successful fetch (then cached 6h). A stale-on-error sets cache + request timeout/retry would soften this.
- **Historic merged rows**: before lots existed, duplicate adds were averaged into one row. Those can't be un-averaged; new purchases keep exact prices.
- **Card image URLs can't be guessed from card ids**: newer sets (Mega Evolution era) are hosted on `images.scrydex.com`, and `images.pokemontcg.io` answers unknown paths with a 404 whose body is a *card-back PNG* that browsers render anyway (no `onerror`). `/portfolio` therefore returns each row's real `image_url` (fetched alongside prices, same cache); the frontend's `getCardImageUrl` guess is only a fallback.
- **Rarity names are era-specific** exact strings (old: "Rare Holo"; Scarlet & Violet: "Double Rare") — a rarity filter + wrong-era set legitimately returns nothing.

## Suggested next steps

1. **Deployment prep** — API base URL (`VITE_API_BASE`) and CORS origins (`CORS_ORIGINS`) are env-configurable now; remaining concern: the caches are in-memory (single-process only).
2. **Scheduled snapshots** — a daily cron/job would make the history chart gap-free instead of depending on visits.
3. **Frontend tests** — the backend routers are covered (`Backend/tests/`); the React pages are not.
4. **Store quantities in snapshots** if "value as held at the time" ever matters for the chart.
5. **Consistent snapshot timezone** — `PortfolioSnapshot.snapshot_date` defaults to `datetime.utcnow` but the daily dedupe compares against local `date.today()` (`portfolio.py`); late-evening visits (observed 23:47 PDT) record snapshots dated *tomorrow*, which then show as a future date on the history chart's axis.

## Gotchas for developers

- Run `npm`/`eslint` commands from `Frontend/mintly/`, not the repo root.
- The eslint react-hooks rules are strict (v7): no synchronous `setState` inside `useEffect` — defer via promise callbacks or timeouts (see `Search.tsx`/`CardDetail.tsx` for the pattern).
- Every backend file save restarts the dev server → wipes the response and price caches → first search/portfolio load after is slow.
- Card searches only return the fields listed in `_CARD_FIELDS` (`card_api.py`). If the frontend `Card` type grows a field, add it there too or it will arrive undefined.
- `Backend/.env` holds real secrets and is gitignored — never commit it or move its values into query strings/logs.
