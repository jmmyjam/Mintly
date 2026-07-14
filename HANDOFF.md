# Mintly — Handoff Document

*Last updated: July 15, 2026*

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
- `card_api.py` — FastAPI app, CORS (origins from `CORS_ORIGINS` env var, comma-separated; defaults to `http://localhost:5173`), card/set proxy endpoints, smart search, in-memory response cache (6-hour TTL, per-process, cleared on every `--reload` restart; covers searches and single-card lookups, keyed per query+page). Card-list endpoints are paginated: they take `?page=` and return an envelope `{data, page, pageSize, totalCount}` (250 cards/page — the upstream max). Card searches pass `select=` upstream (`_CARD_FIELDS`) so responses carry only the fields the frontend uses — a full-set search is ~90KB instead of multiple MB. `/sets/{id}` is answered from the cached sets list with no upstream call. Every card-list and card-detail response goes through `_with_price_changes`, which records a daily price snapshot and attaches a `priceChange` object to each priced card (see `price_history.py`); this is wrapped in try/except so a DB hiccup never breaks the card proxy. Also serves `/cards/{id}/history` (daily points) and `/cards/{id}/ebay-price` (eBay estimate). Upstream calls use a (5s connect, 60s read) timeout; an expired sets cache is served stale if the refresh fails.
- `auth.py` — register/login, JWT creation/validation (`get_current_user` dependency), password rules.
- `portfolio.py` — portfolio CRUD, batched price fetching, daily price snapshots, history endpoint. `fetch_prices` resolves all held cards in one upstream OR-query (`id:"a" OR id:"b" …`, chunks of 100) and caches per-card prices for 15 minutes (`_price_cache`); `/portfolio/add` seeds that cache from the card it already fetched. Each `/portfolio` row also carries a `price_change` (today vs the most recent prior snapshot, via `price_history.previous_prices`). Price/snapshot helpers now live in `price_history.py`.
- `price_history.py` — the shared snapshot layer over `card_price_snapshot`: `extract_price` (variant preference order), `record_snapshots` (≤1 row per card per UTC day), `previous_prices` (each card's most recent snapshot strictly before today), `price_change`, `annotate_price_changes` (records today + attaches `priceChange` to a list of card dicts, in place), and `card_history` (daily points for one card over a day window). Because card_api annotates every browsed card, snapshots accumulate for anything users search or view — not just portfolio holdings.
- `snapshot_all.py` — standalone daily job that records a price snapshot for **every** card, so history is gap-free instead of only covering browsed/held cards. Pages the full card list (`GET /cards?select=id,tcgplayer`, ~20k cards / ~82 pages of 250), extracts each price, and calls `record_snapshots` in chunks. Upstream flakes with transient 404s/timeouts, so each page is retried up to 3× with backoff and a still-failing page is **skipped, not fatal** — the crawl finishes the other ~80 and flags itself incomplete (missing cards get caught next run). Idempotent (per-UTC-day dedupe). No FastAPI app needed — it uses `database.SessionLocal` + its own upstream session. `--max-pages N` limits the crawl for smoke tests. A full run is slow (upstream latency, not payload). Scheduled by a launchd LaunchAgent (see "Daily snapshot job" below).
- `ebay_prices.py` — recent-eBay-sold price estimate for cards TCGPlayer can't price. `estimate(name, number, set_name)` builds a keyword query (`"<name> <number> -psa -bgs -cgc"`), fetches the completed-and-sold search page, parses it, and summarizes; results cached 12h (`_cache`). `_fetch_sold_html` seeds cookies from the eBay homepage then requests the search with a Referer, retrying once if it gets the bot-challenge page (`_looks_blocked`: the block page is a tiny "Error Page | eBay", a real page is ~1MB+). `parse_sold` walks `.su-card-container` tiles (BeautifulSoup + html.parser), reads the title from the image `alt`, the date from the "Sold <date>" caption, and the price *after* that caption (a leading price would be shipping/a range low), and drops graded/lots/proxies by title. `summarize` takes the most recent 25 sales, trims comps outside [0.35×, 3×] the median, and returns median/average/low/high/count/date-range/`source_url`/sample. Every failure path returns `count:0` — never raises.
- `models.py` — SQLAlchemy models.
- `database.py` — engine/session setup from `DATABASE_URL`.
- `tests/` — pytest suite for the auth, portfolio, card-search, price-history, and eBay routers (71 tests, runs offline in ~10s). `conftest.py` sets `DATABASE_URL`/`SECRET_KEY` env vars **before** importing app modules (they read config at import time), overrides `get_db` with an in-memory SQLite session, and swaps `portfolio._session` for a `FakeUpstream` — no Postgres or network needed. `test_search.py`/`test_history.py` likewise swap `card_api.session` for a paged/priced fake; `test_ebay.py` monkeypatches `ebay_prices._fetch_sold_html` and parses fixture HTML. Dev deps: `requirements-dev.txt`.
- Schema is managed by **Alembic** (`alembic/versions/`); `env.py` reads `DATABASE_URL` from `Backend/.env` and targets `models.Base.metadata`, so `alembic revision --autogenerate` works. The app no longer calls `create_all` at startup — after changing `models.py`, generate a migration, review it, and run `alembic upgrade head`. Databases created under the old `create_all` regime were stamped at the initial revision (`alembic stamp head` before the first real migration).

### Data model
- `users` — id, email, username, hashed_password (bcrypt), created_at, accepted_terms_at (when the user accepted the ToS at registration; NULL for accounts predating the requirement).
- `portfolio_cards` — one row per **purchase (lot)**: user_id, card_id (TCG API id like `base1-4`), card_name, quantity, purchase_price, purchase_date. The same card bought twice = two rows; the frontend groups them visually.
- `card_price_snapshot` — one row per card per UTC day: card_id, price, snapshot_date. Shared across users, with a composite `(card_id, snapshot_date)` index. Written by the daily `snapshot_all.py` job (every card), and also whenever any user loads their portfolio **or browses a priced card** through a card endpoint (all deduped per UTC day). It is the app-wide price-history store; portfolio value-over-time is derived from it by filtering to a user's holdings (`/portfolio/history`), so there is no separate portfolio-snapshot table. (Renamed from `portfolio_snapshot` — migration `b7e1c4d9f2a3` renames the table and its indexes in place, preserving rows.)
- All `DateTime` columns store **naive UTC**, set via the shared `utcnow()` helper in `models.py`; anything compared against them (e.g. the snapshot dedupe in `portfolio.py`) must use `utcnow()` too, never local time. They serialize without a zone suffix, so the frontend must anchor them with `Z` before parsing (`parseUTCDate` in `Portfolio.tsx`) — a bare `new Date(...)` reads them as local time and shows evening purchases dated tomorrow.

### API endpoints
| Endpoint | Notes |
|---|---|
| `POST /auth/register` | JSON body (never query params — passwords would hit logs). Password rules: ≥8 chars, ≥1 letter, ≥1 number. Requires `accepted_terms: true` (400 "You must agree to the Terms of Service" otherwise — message mirrored by the register form's checkbox); acceptance time stored on the user. |
| `POST /auth/login` | OAuth2 form body; accepts email **or** username. Returns a 7-day JWT. |
| `GET /search?q=&page=` | Smart search — see below. Returns `{data, page, pageSize, totalCount}` (250/page); priced cards carry a `priceChange`. |
| `GET /cards?name=&set_id=&number=&rarity=&type=&page=` | Filtered search; drives the frontend filter bar. Same paged envelope, same `priceChange`. |
| `GET /cards/{card_id}` | Single card; drives the detail page. Cached (6h). Carries `priceChange` when a prior snapshot exists. |
| `GET /cards/{card_id}/history?days=` | Daily price points `[{date, price}]` from Mintly's snapshots. `days` defaults to 1825 (~5 years), clamped 1–3650. |
| `GET /cards/{card_id}/ebay-price` | Recent-eBay-sold estimate `{count, median, average, low, high, currency, since, until, source_url, sample}`. `count:0` when nothing usable. Best-effort scrape (12h cache). |
| `GET /sets`, `GET /sets/{id}`, `GET /sets/{id}/cards?page=` | Sets list is cached; single sets served from it; drives filter dropdown + default view. Set-cards responses carry `priceChange` too. |
| `GET /portfolio` | Auth. Returns one row per lot with live price, P&L, daily `price_change`, and the card's real `image_url` (all fetched in one batched upstream call, 15-min cache). Also records today's snapshots as a side effect. |
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
- `Home.tsx` — landing page: split hero with oversized headline, `HeroSearch` (search pill with a typewriter placeholder cycling example queries; submits to `/search?q=`, plus quick-search chips), divider + supporting copy on the left and a fanned spread of Base Set card images on the right (hidden under 960px); numbered feature cards; cream CTA band linking to the portfolio. App-wide layout: a dark outer frame (`--frame`) with all routes rendered on one large rounded panel (`.main`); the sticky navbar merges into the frame (translucent + blurred) — favicon leaf logo + wordmark on the left, the nav pill centered on the screen (3-column grid), auth button on the right. It auto-hides: slides up when scrolling down past 80px, slides back on any upward scroll (`navbar-hidden` class toggled by a scroll listener in `Navbar.tsx`).
- `Search.tsx` — debounced (400ms) search-as-you-type; seeds its query from `?q=` on mount (how the home hero search lands here — the debounce effect then runs it automatically); filter bar (set/rarity/type/number → `/cards`, otherwise `/search`); shows the newest set by default when empty; "add to portfolio" inline form. Each tile shows the price with a `DayChange` chip below it when the card carries a `priceChange`. Multi-page results get a Prev/Next pager (above and below the grid); any query/filter change resets to page 1, and page moves skip the debounce.
- `CardDetail.tsx` — route `/card/:cardId`; large image, a prominent current market price with its `DayChange`, set/rarity/type/HP/artist facts, full price-variant table (low/mid/high/market), a `PriceHistoryChart`, and an add form with the price pre-filled. When the card has no TCGPlayer price it fetches `/cards/{id}/ebay-price`, renders an `EbayEstimate` block, and seeds the add form with the eBay median (so priceless cards are still addable). Linked from search results and portfolio tiles.
- `Portfolio.tsx` — summary stats, value-over-time area chart, card grid grouped by card with expandable per-purchase (lot) breakdown; inline edit per lot. Each group's "Now" price shows a `DayChange` chip (from the row's `price_change`). Removing a lot is a two-step inline confirm (Remove → "Confirm remove"/Cancel; ✕ → Remove/Cancel on lot rows), and remove/edit failures render as inline `StatusMessage` error lines next to the affected lot (self-clearing after 4s) — no native `confirm()`/`alert()`. Renders as soon as the portfolio arrives; the history chart fills in when the (deliberately later) history call returns. Client-side toolbar above the grid: name filter, gainers/losers filter, and sort (recently added [default] / highest value / biggest gain / biggest loss / name) — all computed per card *group*; cards without price data sort last and match neither gainers nor losers. Summary stats always reflect the full portfolio, not the filtered view.
- `Login.tsx` — combined login/register with client-side password validation mirroring the backend. Shows a notice when redirected here via router state — "Your session expired…" (from `useSessionRedirect`) or "You've been logged out successfully." (from the Navbar's Logout button).
- `Terms.tsx` / `Privacy.tsx` — static legal pages (routes `/terms`, `/privacy`), linked from the `Footer` component, which renders on every page on the outer frame below the content panel (mirroring the navbar's chrome-on-frame placement): brand, quick links, unofficial-fan-project/trademark disclaimer, "prices are informational only" note, © line. Keep the legal pages in sync with behavior changes (see CLAUDE.md convention).
- `api.ts` — all fetch calls. `authedFetch` wraps authenticated requests: any 401 clears the stored token and throws `SessionExpiredError`; pages catch it and redirect to `/login` with that notice (via `useSessionRedirect`). Token lives in `localStorage`.

### Shared frontend modules
- `src/components/` — `Navbar`, plus the pieces the pages share: `PriceQtyForm` (the price+quantity form behind Search's inline add, CardDetail's labeled add, and Portfolio's lot editor — props switch labels, button size, busy state, optional Cancel), `StatRow` (label/value `price-row` line), `GainLoss` (signed, colored dollar amount with optional percent), `DayChange` (compact daily price-change chip — arrow + amount + percent, green/red/muted; on search tiles, CardDetail, and Portfolio), `PriceHistoryChart` (per-card recharts area chart from `/cards/{id}/history`, with 1M/6M/1Y/All range buttons that filter the fetched series client-side — remount per card with `key={cardId}` so `loading` resets without a synchronous `setState` in the effect), `EbayEstimate` (presentational eBay-sold estimate block), `PageMessage` (centered full-page loading/error/logged-out state with optional CTA link), `StatusMessage` (inline success/error status line — the post-add message in Search/CardDetail and Portfolio's lot edit/remove errors). New page UI that matches one of these should reuse it, not re-inline the markup.
- `src/hooks.ts` — `useAddCard`: the whole add-to-portfolio flow (token check → `/login` redirect, price/qty parsing, self-clearing status message — 3s success / 4s error, busy flag) shared by Search and CardDetail; `useSessionRedirect`: the single source of the "Your session expired — please log in again." redirect — every authed flow must use it so the notice stays in sync with `Login.tsx`.
- `src/format.ts` — `money()`: `$12.34`, or an em dash for missing values.
- `api.ts` types/calls for the price features: `PriceChange` (`{amount, percent, since}`, on `Card.priceChange` and `PortfolioCard.price_change`), `PricePoint`, `EbayEstimate`; `getCardHistory(cardId, days?)` and `getEbayEstimate(cardId)` (both unauthenticated).

## Daily snapshot job

`snapshot_all.py` records a price snapshot for every card so history is gap-free. On this dev Mac it runs daily at **6:00am** via a launchd LaunchAgent (`~/Library/LaunchAgents/com.mintly.daily-snapshot.plist`). Output goes to `~/Library/Logs/mintly-daily-snapshot.log`. It needs the Postgres in `DATABASE_URL` running; if the Mac is asleep at 6am, launchd runs it on the next wake.

**macOS TCC / Full Disk Access (required).** The repo lives under `~/Documents`, which macOS protects — a launchd job can't read files there by default, so a scheduled run fails immediately with `Operation not permitted`. The plist therefore invokes the **framework Python directly** (`/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14`, which is outside `~/Documents` so launchd can exec it), with `PYTHONPATH` pointing at the repo venv's `site-packages` and `WorkingDirectory` set to `Backend/` (so `.env` loads and `import database` resolves). That python binary must be granted **Full Disk Access** so it can read the project:
1. System Settings → Privacy & Security → Full Disk Access → **+**
2. In the file dialog press **⌘⇧G**, paste `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14`, add it, and toggle it **on**.
3. `launchctl kickstart gui/$(id -u)/com.mintly.daily-snapshot` and confirm the log shows `page 1/82 …` instead of the permission error.

(Alternative to granting FDA: move the repo out of `~/Documents`, e.g. to `~/GitHub`, and repoint the plist — then no special permission is needed.)

Managing it:
```bash
launchctl load   ~/Library/LaunchAgents/com.mintly.daily-snapshot.plist   # enable
launchctl unload ~/Library/LaunchAgents/com.mintly.daily-snapshot.plist   # disable
launchctl kickstart gui/$(id -u)/com.mintly.daily-snapshot                # run now
launchctl kill  TERM gui/$(id -u)/com.mintly.daily-snapshot               # stop a run
launchctl list | grep mintly                                             # status (col 1 = PID if running, col 2 = last exit)
tail -f ~/Library/Logs/mintly-daily-snapshot.log                         # watch output
```
The plist is machine-specific (absolute paths) and lives outside the repo; the job script is in `Backend/`. To change the time, edit `StartCalendarInterval` in the plist and `unload`/`load` it. To run it by hand from a terminal (which already has Documents access), just `cd Backend && venv/bin/python snapshot_all.py`.

## Behaviors worth knowing

- **Price picking**: first available `mid` among holofoil → normal → reverseHolofoil → 1stEditionHolofoil (`extract_price` backend, `getCardPrice` frontend — keep in sync).
- **History chart**: computed against *current* holdings, so editing a quantity retroactively changes past points. Snapshots only record on days someone loads their portfolio. With <2 days of data the chart shows a flat placeholder line at today's value. Snapshot days are UTC, so a late-evening US visit records under the next calendar day's UTC date — the chart's newest point can read one day ahead of local; dedupe and chart bucketing use the same UTC day, so points stay one-per-day.
- **Newest sets can lack TCGPlayer prices**: the upstream API lags on 2026 "Mega Evolution" era sets (was 0/N for me4, me3, me2pt5). It backfills over time — `me1` is now fully priced — but later sets may still be empty. The UI shows a "prices unavailable" note when a whole result set is priceless; blank-price adds are rejected unless a purchase price is given. Not a bug — upstream data lag.
- **eBay fallback for priceless cards**: `/cards/{id}/ebay-price` estimates a value from recent *sold* eBay listings for cards TCGPlayer can't price. CardDetail shows it and pre-fills the add form with the median, so those cards are still addable. The estimate is the median/average of the most recent ~25 ungraded single-card sales, with graded slabs/lots/proxies excluded by title and far-off outliers trimmed around the median. eBay markup and bot checks change, so treat `count:0` as normal, not an error. Verified live (e.g. Mega Lucario ex 188 → ~$250 median from ~20 recent sales).
- **Daily price change**: any priced card browsed through a card endpoint gets a snapshot, and responses carry `priceChange` (today vs the most recent prior-day snapshot: `{amount, percent, since}`). `/portfolio` rows carry the same as `price_change`. The frontend renders it as a `DayChange` chip next to the price — so a card's daily move is visible without opening or adding it. It's absent until at least one prior-day snapshot exists for that card.
- **Per-card price history**: `/cards/{id}/history` returns Mintly's own daily snapshots (there is no upstream history endpoint). The daily `snapshot_all.py` job records a point for every card each day, so charts fill in one day at a time for the whole catalog going forward — but depth is still bounded by how long the job has been running (snapshots start July 14, 2026), so charts are short until it accumulates. The default window is ~5 years; the chart shows a "not enough history yet" note with fewer than two points.
- **Add button** shows "Adding…" and blocks double-clicks (the add round-trips to the external API, 1–3s).
- **Session expiry**: JWTs last 7 days. Any authed call after expiry gets a 401 → token cleared → redirect to `/login` with a "session expired" notice (`SessionExpiredError` in `api.ts`, redirect via `useSessionRedirect` in `hooks.ts`).
- **Upstream latency dominates cold requests**: a never-cached search can take the upstream API tens of seconds; caching + `select=` trimming make repeats fast but can't fix the first hit. Portfolio loads are one batched call regardless of collection size (measured ~0.8s cold, ~4ms warm for 5 cards).
- **Upstream is occasionally flaky, not just slow**: observed (July 10, 2026) `GET /sets` transiently returning 404 and taking ~50s when it did succeed. All upstream calls now carry a (5s connect, 60s read) timeout so a hung connection can't pin a worker, and the sets cache is served stale when a refresh fails — so `/search` keeps working through flakes once the sets list has been fetched at least once since process start. A flake on a *cold* cache (fresh process, first request) still surfaces as `{"detail": "Failed to fetch sets"}`; there is no retry, only the next request trying again. `fetch_prices` skips failed/timed-out chunks, so `/portfolio` degrades to missing prices instead of erroring.
- **Historic merged rows**: before lots existed, duplicate adds were averaged into one row. Those can't be un-averaged; new purchases keep exact prices.
- **Card image URLs can't be guessed from card ids**: newer sets (Mega Evolution era) are hosted on `images.scrydex.com`, and `images.pokemontcg.io` answers unknown paths with a 404 whose body is a *card-back PNG* that browsers render anyway (no `onerror`). `/portfolio` therefore returns each row's real `image_url` (fetched alongside prices, same cache); the frontend's `getCardImageUrl` guess is only a fallback.
- **Rarity names are era-specific** exact strings (old: "Rare Holo"; Scarlet & Violet: "Double Rare") — a rarity filter + wrong-era set legitimately returns nothing.

## Suggested next steps

1. **Deployment prep** — API base URL (`VITE_API_BASE`) and CORS origins (`CORS_ORIGINS`) are env-configurable now; remaining concern: all in-memory state is single-process only (the search/price caches, `ebay_prices._cache`, and the `ebay_prices._session` cookie jar). Multiple workers each scrape/cache independently.
2. **Scheduled snapshots** — done on this dev Mac via a launchd LaunchAgent running `snapshot_all.py` daily (see "Daily snapshot job"). For a deployed environment, replace the LaunchAgent with a server-side cron / systemd timer / cloud scheduler running the same script against the production DB (a Claude cloud routine can't reach a local Postgres).
3. **Frontend tests** — the backend routers are covered (`Backend/tests/`, 71 tests); the React pages are not.
4. **Store quantities in snapshots** if "value as held at the time" ever matters for the chart.
5. **eBay scraping robustness** — the estimate depends on eBay's `.su-card-container` markup and unauthenticated access; consider eBay's official Browse/Marketplace API or a headless fallback if the scrape starts getting blocked or the layout changes.

## Gotchas for developers

- Run `npm`/`eslint` commands from `Frontend/mintly/`, not the repo root.
- The eslint react-hooks rules are strict (v7): no synchronous `setState` inside `useEffect` — defer via promise callbacks or timeouts (see `Search.tsx`/`CardDetail.tsx`), or remount the component with a `key` so its state re-initializes instead of being reset in the effect (see `PriceHistoryChart`).
- Every backend file save restarts the dev server → wipes the response and price caches → first search/portfolio load after is slow.
- Card searches only return the fields listed in `_CARD_FIELDS` (`card_api.py`). If the frontend `Card` type grows a field, add it there too or it will arrive undefined. (`priceChange` is added server-side in `_with_price_changes`, not selected upstream.)
- eBay scraping (`ebay_prices.py`) needs a two-step request (homepage for cookies, then the search with a Referer) — a bare request gets a tiny "Error Page | eBay". When changing `parse_sold`, verify against a freshly fetched sold-listings page: `.su-card-container` tiles, title in the image `alt`, and the price *after* the "Sold <date>" caption.
- `Backend/.env` holds real secrets and is gitignored — never commit it or move its values into query strings/logs.
