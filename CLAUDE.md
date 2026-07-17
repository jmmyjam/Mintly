# CLAUDE.md

Mintly — Pokemon TCG portfolio tracker. FastAPI + PostgreSQL backend, React 19 + TypeScript + Vite frontend. External data from the Pokemon TCG API (pokemontcg.io); prices via TCGPlayer fields in its responses.

Start every chat message to the user with their name, Jimmy.

Full architecture, endpoint reference, and known behaviors: @HANDOFF.md

## Commands

Backend (run from `Backend/`, uses `venv/`):
```bash
venv/bin/uvicorn app.main:app --reload   # dev server on :8000, docs at /docs
venv/bin/python -m py_compile <file>.py  # quick syntax check
venv/bin/alembic upgrade head            # apply DB migrations
venv/bin/alembic revision --autogenerate -m "..."  # new migration after model changes
venv/bin/pytest tests/ -q                # run backend tests (offline: sqlite + fake upstream)
venv/bin/python scripts/snapshot_all.py          # snapshot every card's price into history (daily job; --max-pages N to limit, --max-ebay N caps the eBay fill (0 skips), --ebay-pause S paces it)
```

A LaunchAgent (`~/Library/LaunchAgents/com.mintly.daily-snapshot.plist`) runs `scripts/snapshot_all.py` daily at 6am, logging to `~/Library/Logs/mintly-daily-snapshot.log` — see HANDOFF for load/kickstart commands. It needs the Postgres in `DATABASE_URL` running. Because the repo lives under `~/Documents` (macOS TCC-protected), the agent invokes the framework Python directly and that binary must be granted **Full Disk Access** or every scheduled run fails with "Operation not permitted" (see HANDOFF "Daily snapshot job").

Frontend (run from `Frontend/mintly/` — NOT the repo root):
```bash
npm run dev        # Vite dev server on :5173
npm run build      # tsc + vite build — use this to verify changes compile
npx eslint src/    # lint
```

Backend tests live in `Backend/tests/` (auth, portfolio, card-search, price-history, eBay + the snapshot crawl). `conftest.py` swaps the DB for in-memory SQLite and replaces `portfolio._session` with a fake upstream (`test_search.py`/`test_history.py` do the same for `cards.session`; `test_ebay.py` fakes `ebay_prices._fetch_sold_html`) — set env vars / fakes BEFORE importing app modules (they read config at import time). The frontend has no tests yet.

## Structure

- `Backend/app/main.py` — app assembly only: FastAPI app, CORS (`CORS_ORIGINS`), includes the auth/portfolio/cards routers. This is the uvicorn target (`app.main:app`).
- `Backend/app/routers/cards.py` — card/set proxy endpoints, smart search, response cache (`_cache`, covers searches + single cards, keyed per query+page; fresh 6h, then served stale with a single background refresh per key, dead after 24h; mirrored to `Backend/.cache/cards` and restored at startup so restarts don't go cold — `CARD_CACHE_DIR` overrides the dir; `/sets/{id}` is answered from the cached sets list). Every card-list/detail response is passed through `_with_price_changes` (records a daily snapshot + attaches `priceChange`); also serves `/cards/{id}/history` and `/cards/{id}/ebay-price`. Upstream calls take `timeout=_TIMEOUT` (5s connect/60s read — keep it on any new call); the sets cache is served stale if a refresh fails.
- `Backend/app/routers/auth.py` — register/login, JWT, `get_current_user` dependency, password rules
- `Backend/app/routers/portfolio.py` — portfolio CRUD, batched price fetching (`fetch_prices`, one upstream call per 100 cards, 15-min `_price_cache`; card image URLs ride along — never guess them from card ids, see HANDOFF), daily snapshots, history endpoint; each row carries `price_change` (daily) via `previous_prices`
- `Backend/app/services/price_history.py` — shared snapshot store: `extract_price`, `recorded_today` (card ids already snapshotted this UTC day), `record_snapshots` (one row per card per UTC day), `previous_prices` (most recent prior-day snapshot per card), `annotate_price_changes` (adds `priceChange` to card dicts), `card_history`. Used by both the cards and portfolio routers — snapshots are recorded for ANY browsed card, not just held ones.
- `Backend/app/services/ebay_prices.py` — recent-eBay-sold price estimate for cards TCGPlayer can't price. Scrapes the sold-listings HTML (BeautifulSoup, `.su-card-container` tiles), drops graded/lots/proxies, and returns median/average of the most recent ungraded sales (12h `_cache`). Best-effort: any failure returns `count:0`. See HANDOFF for the fetch/parse specifics.
- `Backend/scripts/snapshot_all.py` — standalone daily job: pages the full Pokemon TCG card list (`select=id,name,number,set,tcgplayer`) and records a `card_price_snapshot` for every priced card, so history is gap-free instead of only covering browsed/held cards. Cards with NO TCGPlayer price then get an eBay sold-median snapshot instead (newest sets first, skipping cards already snapshotted today; paced `--ebay-pause` seconds/scrape (default 5), capped at `--max-ebay` (default 2000 — above the ~1.6k priceless count, so all are attempted; 0 = skip). Sale-less cards record nothing and never stop the pass; only 5 straight FAILED fetches (bot block) end it early. Idempotent (per-UTC-day dedupe via `record_snapshots`); a flaky page is retried inline, then re-tried in an end-of-run second pass — only a page failing both passes is dropped (run flagged incomplete), never aborting the crawl. Talks straight to the DB + upstream — the app need not be running. Scheduled via launchd (see HANDOFF).
- `Backend/app/models.py` — SQLAlchemy models; schema is managed by Alembic (`alembic/versions/`), NOT `create_all` — model changes need a migration. `card_price_snapshot` (one row per card per UTC day, composite `(card_id, snapshot_date)` index) is the app-wide price history for any browsed-or-held card; portfolio value-over-time is derived from it, there is no separate portfolio-snapshot table.
- `Frontend/mintly/src/api.ts` — ALL fetch calls live here; pages never call `fetch` directly
- `Frontend/mintly/src/pages/` — Search, CardDetail, Portfolio, Login, Home, Terms, Privacy (legal pages linked from the Footer)
- `Frontend/mintly/src/components/` — shared UI: Navbar, Footer (brand, links, Pokemon/TCGplayer/eBay trademark disclaimer, © line — rendered on every page, on the frame below the panel), HeroSearch (home hero search pill, typewriter placeholder, navigates to `/search?q=`), PriceQtyForm (price+qty add/edit form), StatRow (label/value line), GainLoss (signed colored amount), DayChange (compact daily price-change chip, green/red/flat — used on search tiles, CardDetail, Portfolio), PriceHistoryChart (per-card price tracker: recharts area chart of daily snapshots, 1M/6M/1Y/All range toggle — remount it with `key={cardId}`), EbayEstimate (recent-eBay-sold estimate block, presentational), PageMessage (centered page state), StatusMessage (inline success/error status line — add flows, Portfolio lot errors). Reuse these instead of re-inlining their markup in pages.
- `Frontend/mintly/src/hooks.ts` — `useAddCard` (full add-to-portfolio flow: token check, parsing, timed status) and `useSessionRedirect` (the 401 → `/login` redirect + notice). `format.ts` — `money()` dollar formatting.
- `Frontend/mintly/src/App.css` — single stylesheet; use the CSS variables from `index.css` (`--bg-card`, `--border`, `--text`, `--text-h`, `--accent`, `--positive`, `--negative`, `--ink`). Theme is dark/minimal with a framed layout: a neutral near-black outer frame (`--frame`) that the translucent navbar merges into (favicon leaf logo + screen-centered nav pill), with all page content on one big rounded graphite panel (`.main`, `--bg`); cream (`--cream`) primary buttons with ink text, mint accent — keep new UI inside this palette.

## Conventions & invariants

- One `portfolio_cards` row = one purchase (a "lot"). Same card bought twice = two rows; the Portfolio page groups them by `card_id`. Do NOT merge rows or average prices on add.
- Credentials/secrets never go in query strings (they end up in server logs). Register uses a JSON body; keep it that way.
- Price-variant preference order (keep backend `extract_price` in `app/services/price_history.py` and frontend `getCardPrice` in sync): holofoil → normal → reverseHolofoil → 1stEditionHolofoil, using `market` (falling back to `mid` when absent).
- TCG API query syntax: multi-word `name:` filters MUST be quoted (`name:"pikachu vmax"`) — bare words after a filter return HTTP 400 upstream. Free-text query parts (search text, `name`, set ids) are lowercased before building the upstream query so case variants share one cache entry; `rarity`/`type` stay exact (era-specific dropdown strings).
- New React components go in `Frontend/mintly/src/components/`, one file per component — don't define reusable components inline in page files. Pages under `src/pages/` are route entries only; if a piece of UI is (or is about to be) used by more than one page, extract it to `components/` first.
- Authenticated frontend calls go through `authedFetch` in `api.ts` (clears token + throws `SessionExpiredError` on 401). Pages catch that error and redirect to `/login` with a notice in router state — new authed flows must do the same, via `useSessionRedirect` from `hooks.ts` (don't hand-roll the redirect/notice).
- Card searches request only the fields the frontend uses (`_CARD_FIELDS` in `app/routers/cards.py`, via the upstream `select=` param). If the frontend `Card` type grows a field, add it there too or it will arrive undefined.
- Card-list endpoints (`/search`, `/cards`, `/sets/{id}/cards`) take `?page=` and return a paged envelope `{data, page, pageSize, totalCount}` (50/page), typed as `CardPage` in `api.ts`. Don't return bare card arrays from new list endpoints.
- Backend validation uses Pydantic models with `Field` constraints (price ≥ 0, quantity ≥ 1); mirror user-facing rules client-side for instant feedback, with identical messages.
- No native `confirm()`/`alert()` dialogs: errors show as inline `StatusMessage` lines (self-clearing, 4s) and destructive actions use inline two-step confirm buttons (see `Portfolio.tsx`).
- Backend datetimes are naive UTC: use `utcnow()` from `app/models.py` for anything stored in or compared against a `DateTime` column (snapshot dedupe is per UTC day) — never `datetime.utcnow()` (deprecated) or local `date.today()`.
- Legal pages track reality: any change affecting what user data is stored, auth/session behavior, third-party data flows, or how prices are sourced/shown must update `Terms.tsx`/`Privacy.tsx` (and their "Last updated" dates) in the same change.

## Gotchas

- eslint react-hooks v7 is strict: no synchronous `setState` inside `useEffect` bodies — set state in promise callbacks, or defer via `setTimeout` (see the debounce effect in `Search.tsx`).
- The card/search `_cache` survives `--reload` restarts (disk mirror, see above); only a never-fetched query pays the upstream cost (a few seconds — upstream latency, not a bug). The portfolio `_price_cache` is memory-only and does reset on restart.
- Upstream latency scales with the *requested* `pageSize`, not the payload: 250/page benchmarks at 20–60s with dropped connections, 50/page at 2–5s. Don't raise `_PAGE_SIZE` in `app/routers/cards.py` without re-measuring (`scripts/snapshot_all.py` keeps its own 250 deliberately — it's a retrying batch job, not a user-facing request).
- Some newer sets (2026 "Mega Evolution" era) can lack TCGPlayer price data upstream — empty `tcgplayer.prices`. The UI handles it, and CardDetail falls back to an eBay sold-listings estimate (prefilling the add form) for those. Upstream backfills over time — e.g. `me1` is now fully priced, but later sets may not be.
- eBay scraping is fragile by nature: `ebay_prices` seeds cookies from the eBay homepage before each search and retries once (eBay blocks cold requests with a tiny "Error Page | eBay"; a real results page is ~1MB+). `parse_sold` depends on eBay's `.su-card-container` markup and takes the price *after* the "Sold <date>" marker — if eBay restructures, it returns nothing and estimates degrade to `count:0`, never an error. Verify parser changes against live HTML.
- `Backend/.env` holds real secrets (DB URL, SECRET_KEY, API key) and is gitignored — don't read it into command output or commit it.
- Schema changes: edit `app/models.py`, then `alembic revision --autogenerate -m "..."`, review the generated file, and `alembic upgrade head`. The app no longer calls `create_all`, so an unapplied migration means missing tables/columns at runtime.
- Always verify with `npm run build` (not just eslint) — the strict tsconfig catches things lint doesn't, e.g. recharts callback param types.
