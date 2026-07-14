---
name: update-docs
description: Sync CLAUDE.md and HANDOFF.md with the current state of the code. Use after completing any notable feature, refactor, schema/endpoint change, or new convention — or whenever the user asks to update the docs/handoff.
---

# Update project docs

Two docs, two different jobs — keep them true to the code without changing their character:

- **CLAUDE.md** — terse operating instructions for coding agents. Loaded into context every session, so every line has a cost. Only commands, structure, conventions, and gotchas that change how an agent should act.
- **HANDOFF.md** — the full handoff: architecture, endpoint reference, observed behaviors, next steps. Detail belongs here, not in CLAUDE.md.

## Process

1. **Establish what actually changed.** Check `git status` / `git diff` (or the work just completed in conversation). Don't guess from memory — verify file paths, function names, and flags exist before writing them into a doc.
2. **Sweep both docs for stale statements**, not just spots to add to. Sections to check:
   - CLAUDE.md: Commands · Structure · Conventions & invariants · Gotchas
   - HANDOFF.md: the `*Last updated:*` line · Running locally · Architecture (backend files, data model, endpoint table) · Smart search · Frontend pages · Shared frontend modules · Behaviors worth knowing · Suggested next steps · Gotchas for developers
3. **Update CLAUDE.md sparingly** — one dense line per new module, convention, or gotcha, in the existing style. If a detail needs more than ~2 lines, put the detail in HANDOFF.md and let CLAUDE.md reference it.
4. **Update HANDOFF.md fully**, and bump `*Last updated:*` to today's date (absolute date, never relative wording).
5. **Keep shared facts in sync.** Some rules appear in both files (e.g. the price-variant preference order, the paged `{data, page, pageSize, totalCount}` envelope, the `useSessionRedirect` requirement). If one changes, change both.
6. **Retire completed "Suggested next steps"** in HANDOFF.md — remove or rewrite items the change addressed; don't leave done items listed as pending.

## Rules

- Docs describe **current state**, not history. No "recently changed", "now uses", changelog-style entries, or references to who/when — git records that.
- Match the existing voice: declarative, dense, em dashes, tables kept as tables, exact strings quoted.
- **Never delete a gotcha or "behavior worth knowing" unless the fix is verified in the code** — these encode hard-won debugging knowledge (upstream flakiness, card-back-PNG 404s, timezone snapshot bug). When a fix is verified, remove the item or rewrite it as the new behavior.
- Don't reformat or rewrap sections the change doesn't touch.
- Never copy values from `Backend/.env` (or any secret) into either doc.

## Done when

Someone reading only CLAUDE.md + HANDOFF.md — without the git log or this conversation — would work with the codebase as it is now, hitting no instructions that point at moved, renamed, or deleted things.
