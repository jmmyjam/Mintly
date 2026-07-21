# Mintly

A Pokemon TCG portfolio tracker. Search cards, monitor live market prices, and track your collection's value over time.

## Stack

- **Backend** — FastAPI, PostgreSQL, SQLAlchemy, JWT auth
- **Frontend** — React, TypeScript, Vite, React Router

## Features

- Search cards by name, set, or card number
- Live prices pulled from TCGPlayer via the Pokemon TCG API
- Real TCGplayer prices for brand-new sets the Pokemon TCG API hasn't priced yet, filled daily from [TCGCSV](https://tcgcsv.com) (a nightly mirror of TCGplayer's price data) — variant-accurate, so a 5¢ common shows as 5¢
- eBay sold-listings estimate as the last resort for cards neither source can price (shown on the card page, and used by the daily snapshot job so those cards get history too)
- Per-card price history chart and daily price-change chips, built from Mintly's own daily snapshots
- Portfolio tracking with gain/loss per card and a value-over-time chart
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

3. Create the database and apply migrations:
   ```bash
   psql postgres -c "CREATE DATABASE mintly;"
   alembic upgrade head
   ```

4. Start the server:
   ```bash
   uvicorn app.main:app --reload
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

## Price history & the daily snapshot job

Mintly builds its own price history — there is no upstream history API. One row per card per UTC day lands in `card_price_snapshot`, written by `Backend/scripts/snapshot_all.py`, which runs in four phases:

1. **TCGPlayer crawl** — pages the full card list (~20.5k cards) and snapshots every priced card. Flaky pages are retried inline, then again in an end-of-run second pass; a page has to fail both to be skipped.
2. **TCGCSV fill** — cards with no TCGPlayer price (~1.6k: brand-new sets plus old oddballs) get real TCGplayer prices from the TCGCSV mirror, matched by set + card number and stored in the catalog like any other price — so newest-set cards browse as normally-priced cards, variant table and all.
3. **eBay fill** — whatever TCGCSV couldn't match gets the median of its recent eBay *sold* listings instead, newest sets first, paced 5s between scrapes. Cards with too few recent sales record nothing; only 5 consecutive failed fetches (bot block) stop the pass early.
4. **Compaction to cold storage** — see the next section.

```bash
cd Backend
venv/bin/python scripts/snapshot_all.py                       # full run by hand (crawl ~30min; the eBay tail depends on what TCGCSV leaves over)
venv/bin/python scripts/snapshot_all.py --max-pages 2 --max-ebay 0 --no-tcgcsv   # quick smoke test
# flags: --max-pages N     stop the crawl after N pages (0 = all)
#        --no-tcgcsv       skip the TCGCSV price fill
#        --max-ebay N      cap eBay estimates (default 2000; 0 = skip)
#        --ebay-pause S    seconds between eBay scrapes (default 5)
#        --no-compact      skip the cold-storage step
```

It's scheduled daily at **1:00pm local** by a launchd LaunchAgent (`~/Library/LaunchAgents/com.mintly.daily-snapshot.plist`) — just after TCGCSV's daily 20:00 UTC refresh, so the fill reads same-day prices — logging to `~/Library/Logs/mintly-daily-snapshot.log`. Postgres must be running; if the Mac is asleep at 1pm it runs on the next wake. The Python binary in the plist needs **Full Disk Access** because the repo lives under `~/Documents` — see HANDOFF.md "Daily snapshot job" if runs fail with "Operation not permitted".

```bash
launchctl load   ~/Library/LaunchAgents/com.mintly.daily-snapshot.plist   # enable
launchctl unload ~/Library/LaunchAgents/com.mintly.daily-snapshot.plist   # disable
launchctl kickstart gui/$(id -u)/com.mintly.daily-snapshot                # run now
launchctl list | grep mintly                                              # status
tail -f ~/Library/Logs/mintly-daily-snapshot.log                          # watch a run
```

### Tiered history storage (stock-chart style)

Left alone, daily snapshots would grow the database ~1.1GB/year forever. Instead, history is tiered like stock-market data — and old data is **offloaded, never deleted**:

- **Last ~30 days** — full daily rows in Postgres (charts' 1M range stays daily-resolution).
- **Older months** — the DB keeps one row per card per month (its month-end "close"), so 6M/1Y/All chart ranges show monthly points. Keeps the DB to ~36MB/year.
- **The full old dailies** — exported to `Backend/.archive/price-history/YYYY-MM.csv.gz` (~3–6MB/month, gitignored) *before* the DB copy is thinned; the archive file must exist on disk before a single row is removed. Back this folder up — the DB alone no longer holds full history.

The snapshot job compacts automatically each day (a month becomes eligible once it's complete and 30+ days old). Manual controls:

```bash
cd Backend
venv/bin/python scripts/archive_history.py                    # compact eligible months now
venv/bin/python scripts/archive_history.py --list             # what's archived, with sizes
venv/bin/python scripts/archive_history.py --restore 2026-05  # load a month's dailies back into the DB
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register` | Create account |
| POST | `/auth/login` | Login, returns JWT |
| GET | `/search?q=` | Natural language card search |
| GET | `/cards?name=&set_id=&number=` | Filtered card search |
| GET | `/cards/{card_id}` | Get a single card |
| GET | `/cards/{card_id}/history?days=` | Daily price points from Mintly's snapshots |
| GET | `/cards/{card_id}/ebay-price` | Recent eBay sold-listings estimate |
| GET | `/sets` | List all sets |
| GET | `/sets/{set_id}/cards` | Cards in a set |
| GET | `/portfolio` | Get your portfolio (auth required) |
| GET | `/portfolio/history` | Portfolio value over time (auth required) |
| POST | `/portfolio/add` | Add card to portfolio (auth required) |
| PATCH | `/portfolio/{id}` | Edit a lot's price/quantity (auth required) |
| DELETE | `/portfolio/{id}` | Remove card from portfolio (auth required) |
