import { useEffect, useSyncExternalStore } from 'react'
import { getPortfolios, getToken, type Portfolio } from './api'

// ----- Active-portfolio store ----------------------------------------------------
//
// The app's cross-page "which portfolio am I looking at / adding to" state. Unlike
// accessibility.ts (device-local prefs), the list of portfolios IS account data —
// it's hydrated from the backend (getPortfolios). Only the *active selection* is a
// client concern, persisted to localStorage so it survives a reload.
//
// useSyncExternalStore keeps every consumer (Portfolio header, Scan batch, the
// single-add pickers) in sync. Hydration is lazy + single-flight, like owned.ts:
// the first usePortfolios() call while signed in kicks one getPortfolios().

interface State {
  portfolios: Portfolio[]
  activeId: number | null
  loaded: boolean
}

const ACTIVE_KEY = 'mintly.activePortfolio'

function loadActiveId(): number | null {
  try {
    const raw = localStorage.getItem(ACTIVE_KEY)
    if (raw) {
      const n = parseInt(raw, 10)
      return Number.isNaN(n) ? null : n
    }
  } catch {
    /* storage unavailable — no remembered selection */
  }
  return null
}

function persistActiveId(id: number | null) {
  try {
    if (id == null) localStorage.removeItem(ACTIVE_KEY)
    else localStorage.setItem(ACTIVE_KEY, String(id))
  } catch {
    /* storage full/blocked — the in-memory selection still applies this session */
  }
}

let state: State = { portfolios: [], activeId: loadActiveId(), loaded: false }
const listeners = new Set<() => void>()
let inflight: Promise<void> | null = null

function getSnapshot(): State {
  return state
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function emit() {
  listeners.forEach(l => l())
}

// Keep the remembered active id if it's still one of the user's portfolios;
// otherwise fall back to the default portfolio (or the first). Guards against a
// stale id from a previous session or a different account on this browser.
function reconcileActive(portfolios: Portfolio[], desired: number | null): number | null {
  if (desired != null && portfolios.some(p => p.id === desired)) return desired
  const fallback = portfolios.find(p => p.is_default) ?? portfolios[0]
  return fallback ? fallback.id : null
}

// Fetch (or re-fetch) the portfolio list and reconcile the active selection.
// Callers await this after create/rename/delete to refresh the store.
export function refreshPortfolios(): Promise<void> {
  if (!getToken()) return Promise.resolve()
  const p = getPortfolios()
    .then(portfolios => {
      const activeId = reconcileActive(portfolios, state.activeId)
      persistActiveId(activeId)
      state = { portfolios, activeId, loaded: true }
      emit()
    })
    .catch(() => {
      /* leave prior state so a transient failure retries on next use */
    })
    .finally(() => {
      inflight = null
    })
  inflight = p
  return p
}

export function setActivePortfolio(id: number) {
  if (id === state.activeId) return
  persistActiveId(id)
  state = { ...state, activeId: id }
  emit()
}

// Reset on logout / account deletion so the next session starts from its own
// default rather than a leftover selection.
export function clearPortfolios() {
  persistActiveId(null)
  state = { portfolios: [], activeId: null, loaded: false }
  inflight = null
  emit()
}

export interface UsePortfolios {
  portfolios: Portfolio[]
  activeId: number | null
  active: Portfolio | null
  loaded: boolean
  setActive: (id: number) => void
  refresh: () => Promise<void>
}

// Shared, subscription-backed access. Auto-hydrates on first use when signed in.
export function usePortfolios(): UsePortfolios {
  const s = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
  useEffect(() => {
    if (getToken() && !s.loaded && !inflight) refreshPortfolios()
  }, [s.loaded])
  const active = s.portfolios.find(p => p.id === s.activeId) ?? null
  return {
    portfolios: s.portfolios,
    activeId: s.activeId,
    active,
    loaded: s.loaded,
    setActive: setActivePortfolio,
    refresh: refreshPortfolios,
  }
}
