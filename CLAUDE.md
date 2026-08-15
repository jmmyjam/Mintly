# CLAUDE.md

Mintly — Pokemon TCG portfolio tracker. FastAPI + PostgreSQL backend, React 19 + TypeScript + Vite frontend. External data from the Pokemon TCG API (pokemontcg.io); prices via TCGPlayer fields in its responses. Production runs at **https://mintlytcg.com** — Docker Compose on the home server `pikachuserver` behind a Cloudflare Tunnel (see HANDOFF "Production deployment"); this Mac is the dev machine.

Start every chat message to the user with their name, Jimmy.

Deep reference — endpoint table, data model, deployment/backup runbooks, observed behaviors, roadmap — is in `HANDOFF.md` (read it on demand; it is not auto-loaded). Per-directory operating detail is in the nested `CLAUDE.md` files mapped below.

## Where things live

This root file holds only what matters everywhere. Detail lives in directory-scoped `CLAUDE.md` files that Claude Code loads automatically when you work in that tree — so keep a fact in the narrowest file that covers it, and only cross-cutting rules here.

- `Backend/CLAUDE.md` — backend commands, tests, app assembly (`main.py`), data model (`models.py`), deploy + daily-job pointers, backend conventions + gotchas.
  - `Backend/app/routers/CLAUDE.md` — the HTTP routers (auth, cards, portfolio, watchlist, scan, admin, health, sitemap).
  - `Backend/app/services/CLAUDE.md` — the services (card catalog, price history, tcgcsv, ebay, rate limit, mailer, admin access, history archive, watchlist alerts).
  - `Backend/scripts/CLAUDE.md` — the daily snapshot job, history-archive CLI, backup script.
- `Frontend/mintly/CLAUDE.md` — frontend commands, `api.ts`, shared modules, styling, frontend conventions + gotchas. Run npm/eslint from `Frontend/mintly/`, NOT the repo root.
  - `Frontend/mintly/src/pages/CLAUDE.md` — route pages.
  - `Frontend/mintly/src/components/CLAUDE.md` — shared UI components.

## Conventions & invariants (cross-cutting)

These span backend and frontend, or are core domain rules; per-side conventions live in `Backend/CLAUDE.md` / `Frontend/mintly/CLAUDE.md`.

- One `portfolio_cards` row = one purchase (a "lot"). Same card bought twice = two rows; the Portfolio page groups them by **(card_id, grading, grade)** (see the condition bullet). Do NOT merge rows or average prices on add.
- **Condition/grade lives on the lot; graded lots are separate holdings valued at cost.** Each lot carries `grading` (`Raw`/`PSA`/`BGS`/`CGC`/`SGC`/`Other`, NULL = unset) + `grade` (the raw condition for Raw, e.g. `Near Mint`; the slab grade otherwise, e.g. `10`). Shared vocabulary + helpers in `Frontend/mintly/src/grading.ts` (`GRADING_TYPES`, `holdingKey`, `conditionKey`, `isGraded`), kept in sync with backend `GRADING_TYPES` in `app/routers/portfolio.py`; the input is the `GradingPicker` component. The grid groups by holding (`groupByCard` in `portfolio.ts`), so a raw and a graded copy of one card are separate tiles; the Holding route scopes to a holding via a `?g=<conditionKey>` param. Owned-badge (`owned.ts`) and set-completion stay **card_id-based** (condition-agnostic — "do I own this card at all"). A graded lot can't be valued from the raw TCGplayer price, so `GET /portfolio` returns `current_price=null` for it (frontend values it at cost, P&L shows an em dash) and graded adds require an explicit purchase price; real graded pricing is roadmap #7 phase 2. `SlabbedCardImage` renders a graded lot inside a fake slab (grader + grade as real text).
- **Portfolios are named collections** (`portfolios` table; every lot has a `portfolio_id`). A user always keeps ≥1 (the default "My Portfolio", auto-created by `ensure_default_portfolio`); the last one can't be deleted, and deleting a portfolio deletes its lots. The frontend tracks the active one in `src/portfolios.ts` (`usePortfolios()`); `GET /portfolio` with **no** `portfolio_id` returns lots across ALL of a user's portfolios (the account-wide "Owned ×N" badge relies on this) — pass `portfolio_id` to scope. Adds default to the active portfolio; a `PortfolioPicker` can retarget.
- **Card varieties are separate cards; finishes are not.** A card number can carry several TCGplayer *products* — the regular card plus stamped/marked siblings (`[Staff]`, `[W Stamped]`, `(Black Dot Error)`). The daily job's `variety_fill` forks each such sibling into its own synthetic catalog card under id `<base_id>~v<productId>` (`tcgcsv.variety_id`; `~v` never occurs in a real pokemontcg.io id, and everything keys on the string `card_id`, so **no schema change**), searchable/browsable/holdable/charted like any card. *Finishes* (holofoil/reverse/normal/1st-ed) are sub-types of ONE product — they stay on the base card as variant series and never fork. Only same-name products (name-collisions like Mew vs Dark Gyarados excluded) carrying a stamp/mark the base pick lacks fork (`variety_candidates`). Varieties exist only after a crawl (like TCGCSV prices); a synthetic id is never sent upstream (`is_variety_id` guards `cards`/`portfolio`). CardDetail shows an "Other versions" section (via `/cards?set_id=&number=`) cross-linking a card and its varieties, and a "Variety" badge marks a forked card.
- Credentials/secrets never go in query strings (they end up in server logs). Register uses a JSON body; keep it that way.
- Price-variant preference order (keep backend `extract_price` in `app/services/price_history.py` and the frontend's `PRICE_PREFERENCE` in `variants.ts` — which `getCardPrice` reads — in sync): holofoil → normal → reverseHolofoil → 1stEditionHolofoil, using `market` (falling back to `mid` when absent).
- Legal/statement pages track reality: any change affecting what user data is stored, auth/session behavior, third-party data flows, or how prices are sourced/shown must update `Terms.tsx`/`Privacy.tsx` (and their "Last updated" dates) in the same change; likewise any change to accessibility behavior (features, known limitations) must keep `Accessibility.tsx` truthful. The app targets **WCAG 2.1 AA** — real content must clear 4.5:1 contrast (`--text`, not `--text-dim`) and never rely on color alone; see `Frontend/mintly/CLAUDE.md` "Accessibility baseline".
- No em dashes in user-facing copy: never use the `—` character in UI text, page content, emails, or legal pages. Rephrase with commas, periods, or parentheses. Ordinary hyphens in compound words (e.g. `value-over-time`) are fine.
