// A tiny module-level cache of "how many of each card do I own", so the Search
// grid can badge cards already in your portfolio without refetching on every
// mount. One `getPortfolio()` call, reduced to card_id -> total quantity; the
// cache survives navigation between Search and a card, and any add invalidates
// it (see `useAddCard` in hooks.ts).

import { getPortfolio, getToken } from './api'

let cache: Map<string, number> | null = null
let inflight: Promise<Map<string, number>> | null = null

// card_id -> total quantity held. Empty when signed out. Cached across calls;
// concurrent callers share one in-flight request.
export function getOwnedQty(): Promise<Map<string, number>> {
  if (!getToken()) return Promise.resolve(new Map())
  if (cache) return Promise.resolve(cache)
  if (!inflight) {
    inflight = getPortfolio()
      .then(lots => {
        const map = new Map<string, number>()
        for (const l of lots) map.set(l.card_id, (map.get(l.card_id) ?? 0) + l.quantity)
        cache = map
        return map
      })
      .catch(() => new Map<string, number>())
      .finally(() => { inflight = null })
  }
  return inflight
}

// Drop the cache so the next getOwnedQty() refetches — call after any add/remove.
export function invalidateOwned() {
  cache = null
}
