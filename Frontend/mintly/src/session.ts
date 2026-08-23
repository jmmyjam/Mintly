// Per-account client-side caches that must be dropped whenever the signed-in
// identity changes — password login, register, social sign-in, and logout.
// Centralised here so a new cache can't be forgotten at one of those switch
// points: forgetting to clear owned.ts / setCompletion.ts on login/logout let a
// previous account's "Owned xN" badges and set-completion counts leak across a
// same-tab account switch (e.g. a shared or family browser).
import { clearPortfolios } from './portfolios'
import { invalidateOwned } from './owned'
import { invalidateSetCompletion } from './setCompletion'

// Drop every cache keyed to the current account. Call on any identity change,
// after the new token is stored (or the old one cleared) so the next read
// refetches for the right account.
export function clearAccountCaches() {
  clearPortfolios()
  invalidateOwned()
  invalidateSetCompletion()
}
