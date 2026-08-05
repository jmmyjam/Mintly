// A module-level cache of the user's account-wide set completion, so CardDetail
// can show "you own X/Y of this set" without refetching on every card view.
// One `getSetCompletion()` call (no portfolio_id → account-wide, so completion
// counts a card owned in ANY portfolio), cached across navigation; any add
// invalidates it (see `useAddCard` in hooks.ts), alongside owned.ts.

import { getSetCompletion, getToken, type SetCompletion } from './api'

let cache: SetCompletion[] | null = null
let inflight: Promise<SetCompletion[]> | null = null

// The user's per-set completion, account-wide. Empty when signed out. Cached
// across calls; concurrent callers share one in-flight request.
export function getOwnedSetCompletion(): Promise<SetCompletion[]> {
  if (!getToken()) return Promise.resolve([])
  if (cache) return Promise.resolve(cache)
  if (!inflight) {
    inflight = getSetCompletion()
      .then(sets => {
        cache = sets
        return sets
      })
      .catch(() => [] as SetCompletion[])
      .finally(() => { inflight = null })
  }
  return inflight
}

// Drop the cache so the next getOwnedSetCompletion() refetches — call after any
// add/remove.
export function invalidateSetCompletion() {
  cache = null
}
