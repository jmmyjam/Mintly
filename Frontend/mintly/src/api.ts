import { PRICE_PREFERENCE } from './variants'

// ----- Configuration ---------------------------------------------------------

// Set VITE_API_BASE at build time to point at a hosted backend
// (an empty string makes calls relative to the page's own origin).
const BASE: string = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

// ----- Types -------------------------------------------------------------------

export interface PriceVariant {
  low?: number
  mid?: number
  high?: number
  market?: number
}

// Day-over-day change in a card's market price, vs its most recent prior snapshot
export interface PriceChange {
  amount: number
  percent: number | null
  since: string
}

export interface Card {
  id: string
  name: string
  number?: string
  rarity?: string
  artist?: string
  hp?: string
  types?: string[]
  images: { small: string; large: string }
  set: {
    name: string
    id: string
    series?: string
    printedTotal?: number
    releaseDate?: string
  }
  tcgplayer?: {
    url?: string
    updatedAt?: string
    prices?: { [key: string]: PriceVariant }
  }
  // Attached by the backend when a prior snapshot exists (see app/services/price_history.py)
  priceChange?: PriceChange
  // True when the catalog's stored price was stale and the backend kicked off a
  // background re-fetch — CardDetail re-polls until it clears
  refreshing?: boolean
  // For cards TCGPlayer can't price: the most recent snapshot (an eBay
  // sold-median from the daily job). Informational — never a market price.
  estimate?: { value: number; date: string }
  // Set on synthetic "variety" cards — a stamped/marked TCGplayer product (a
  // [Staff] stamp, error print, ...) forked from a base card that shares its
  // number. Holds the base pokemontcg.io card id it was forked from.
  varietyOf?: string
  // Only set on /scan results: the CLIP cosine similarity of this candidate to
  // the captured photo (roughly [-1, 1], higher = closer). Batch scan uses it
  // to flag shaky best-guesses for review.
  matchScore?: number
}

// One daily point in a card's price history (from Mintly's own snapshots)
export interface PricePoint {
  date: string
  price: number
}

// A card's full price history: `points` is the headline series (the preferred
// variant extract_price picks); `variants` holds one series per TCGPlayer
// variant for cards with 2+ priced variants (empty for everything else)
export interface CardHistory {
  points: PricePoint[]
  variants: { [variant: string]: PricePoint[] }
}

// Estimated market value from recent eBay sold listings, for cards the
// TCGPlayer feed can't price. count === 0 means no usable estimate.
export interface EbayEstimate {
  count: number
  median: number | null
  average: number | null
  low: number | null
  high: number | null
  currency: string
  since: string | null
  until: string | null
  source_url: string
  sample: { date: string; price: number; title: string }[]
}

// One page of search results (backend pages at 50 cards — larger upstream pages are drastically slower)
export interface CardPage {
  data: Card[]
  page: number
  pageSize: number
  totalCount: number
}

export interface CardSet {
  id: string
  name: string
  series: string
  releaseDate: string
}

export interface CardFilters {
  name?: string
  number?: string
  // set/rarity/type accept one value or several — a list ORs within that facet
  // (any of the chosen sets/rarities/types); different facets AND together
  set_id?: string | string[]
  rarity?: string | string[]
  type?: string | string[]
}

export interface HistoryPoint {
  date: string
  total_value: number
}

export interface PortfolioCard {
  id: number
  card_id: string
  card_name: string
  quantity: number
  purchase_price: number
  purchase_date: string
  current_price: number | null
  gain_loss: number | null
  gain_loss_pct: number | null
  price_change: PriceChange | null
  image_url: string | null
}

// The logged-in user's account details, shown/edited on the Profile page
export interface UserProfile {
  email: string
  username: string
  created_at: string
  accepted_terms_at: string | null
  // True once the user has confirmed their email via a verification link.
  // Verification is soft (the app works unverified) — this drives the Profile
  // badge + resend control.
  email_verified: boolean
  // True when this account is on the backend's ADMIN_EMAILS list — shows the
  // admin-dashboard link on the Profile page
  is_admin: boolean
}

// Site-wide stats for the admin dashboard (GET /admin/stats, admins only)
export interface AdminStats {
  generated_at: string
  users: { total: number; new_7d: number; new_30d: number; with_portfolio: number }
  signups_by_day: { date: string; count: number }[]
  recent_users: { id: number; username: string; email: string; created_at: string; lots: number }[]
  portfolio: { lots: number; distinct_cards: number; total_quantity: number }
  catalog: { cards: number; stale_prices: number; last_full_sync: string | null }
  snapshots: { rows: number; today: number; latest: string | null }
  db_size_bytes: number | null
}

// Thrown on 401 so pages can redirect to /login instead of showing a generic error
export class SessionExpiredError extends Error {
  constructor() {
    super('Session expired. Please log in again.')
    this.name = 'SessionExpiredError'
  }
}

// Thrown when /admin/stats answers 404 — this account isn't on the admin list
// (the backend deliberately hides the endpoint's existence from non-admins)
export class NotAdminError extends Error {
  constructor() {
    super('Not found')
    this.name = 'NotAdminError'
  }
}

// ----- Token storage -----------------------------------------------------------

export function getToken() {
  return localStorage.getItem('token')
}

export function setToken(token: string) {
  localStorage.setItem('token', token)
}

export function clearToken() {
  localStorage.removeItem('token')
}

// ----- Helpers -------------------------------------------------------------------

// Adds the auth header; a 401 means the token is expired/invalid, so clear it
async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { ...(init.headers || {}), Authorization: `Bearer ${getToken()}` },
  })
  if (res.status === 401) {
    clearToken()
    throw new SessionExpiredError()
  }
  return res
}

// A request that never reached the server rejects with the browser's TypeError
// ("Failed to fetch" / "Load failed") — wording meant for developers. Show this
// instead; messages the API itself returned already read as user-facing text.
export const CONNECTION_ERROR =
  "We couldn't connect. Check your internet connection and try again in a moment."

export function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof TypeError) return CONNECTION_ERROR
  return err instanceof Error && err.message ? err.message : fallback
}

export function getCardImageUrl(cardId: string): string {
  const [setId, number] = cardId.split('-')
  return `https://images.pokemontcg.io/${setId}/${number}.png`
}

// Keep in sync with extract_price in Backend/app/services/price_history.py: market, then mid
export function getCardPrice(card: Card): number | null {
  const prices = card.tcgplayer?.prices
  if (!prices) return null
  for (const type of PRICE_PREFERENCE) {
    const price = prices[type]?.market ?? prices[type]?.mid
    if (price != null) return price
  }
  return null
}

// ----- Auth calls ----------------------------------------------------------------

export async function login(username: string, password: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username, password }),
  })
  if (!res.ok) {
    // 429 carries a "too many attempts" detail — showing "Invalid credentials"
    // for it would send a rate-limited user hunting for a typo
    if (res.status === 429) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || 'Too many login attempts. Please try again in a few minutes.')
    }
    throw new Error('Invalid credentials')
  }
  const data = await res.json()
  setToken(data.access_token)
}

export async function register(email: string, username: string, password: string, acceptedTerms: boolean): Promise<void> {
  const res = await fetch(`${BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, username, password, accepted_terms: acceptedTerms }),
  })
  if (!res.ok) {
    const data = await res.json()
    throw new Error(data.detail || "We couldn't create your account. Please try again.")
  }
}

// The logged-in user's account details (email, username, join date)
export async function getMe(): Promise<UserProfile> {
  const res = await authedFetch('/auth/me')
  if (!res.ok) throw new Error('Failed to load profile')
  return res.json()
}

// Update email and/or username; returns the refreshed profile
export async function updateProfile(updates: { email?: string; username?: string }): Promise<UserProfile> {
  const res = await authedFetch('/auth/me', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || "We couldn't save your changes. Please try again.")
  return data
}

// Change the account password; the backend verifies the current one
export async function changePassword(current_password: string, new_password: string): Promise<void> {
  const res = await authedFetch('/auth/me/password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password, new_password }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.detail || "We couldn't change your password. Please try again.")
  }
  // The backend bumps token_version (revoking every other session) and returns a
  // fresh token for THIS one — swap it in so changing the password doesn't log
  // the current tab out.
  if (data.access_token) setToken(data.access_token)
}

// Re-send the email-verification link to the current user's address (authed).
export async function resendVerification(): Promise<string> {
  const res = await authedFetch('/auth/verify-email/send', { method: 'POST' })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || "We couldn't send the verification email. Please try again.")
  return data.message
}

// Confirm an email address with the token from a verification email (unauthed —
// the link works whether or not the browser opening it is logged in).
export async function verifyEmail(token: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/verify-email`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || "We couldn't verify your email. Please try again.")
  }
}

// Sign out of every OTHER device (kills a leaked token). The backend bumps
// token_version and hands back a fresh token for the current session — store it
// so we stay signed in here.
export async function signOutOtherDevices(): Promise<string> {
  const res = await authedFetch('/auth/me/sign-out-others', { method: 'POST' })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || "We couldn't sign out your other devices. Please try again.")
  if (data.access_token) setToken(data.access_token)
  return data.message
}

// Request a password-reset email. The backend answers identically whether or
// not the address has an account (anti-enumeration), so the returned message
// is always the generic "if that email has an account…" line.
export async function forgotPassword(email: string): Promise<string> {
  const res = await fetch(`${BASE}/auth/forgot-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  const data = await res.json().catch(() => ({}))
  // the only real failure is the 429 rate limit — surface its detail
  if (!res.ok) throw new Error(data.detail || "We couldn't send the reset link. Please try again.")
  return data.message
}

// Set a new password using the token from a reset email (single-use, 30 min)
export async function resetPassword(token: string, new_password: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/reset-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, new_password }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || "We couldn't reset your password. Please try again.")
  }
}

// Permanently delete the logged-in user's account and all their portfolio data.
// Clears the local token on success (the account it points at no longer exists).
export async function deleteAccount(): Promise<void> {
  const res = await authedFetch('/auth/me', { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to delete account')
  clearToken()
}

// ----- Admin calls (admin accounts only) -------------------------------------------

// Site-wide stats for the admin dashboard. 404 = this account isn't an admin.
export async function getAdminStats(): Promise<AdminStats> {
  const res = await authedFetch('/admin/stats')
  if (res.status === 404) throw new NotAdminError()
  if (!res.ok) throw new Error('Failed to load site stats')
  return res.json()
}

// ----- Card calls ----------------------------------------------------------------

export async function searchCards(query: string, page = 1): Promise<CardPage> {
  const res = await fetch(`${BASE}/search?q=${encodeURIComponent(query)}&page=${page}`)
  if (!res.ok) throw new Error('Search failed')
  return res.json()
}

export async function getSets(): Promise<CardSet[]> {
  const res = await fetch(`${BASE}/sets`)
  if (!res.ok) throw new Error('Failed to fetch sets')
  return res.json()
}

export async function getCard(cardId: string): Promise<Card> {
  const res = await fetch(`${BASE}/cards/${encodeURIComponent(cardId)}`)
  if (!res.ok) throw new Error('Card not found')
  return res.json()
}

// Daily price history for one card (Mintly's own snapshots). Default ~5 years.
export async function getCardHistory(cardId: string, days = 1825): Promise<CardHistory> {
  const res = await fetch(`${BASE}/cards/${encodeURIComponent(cardId)}/history?days=${days}`)
  if (!res.ok) throw new Error('Failed to fetch price history')
  return res.json()
}

// Recent-eBay-sold estimate for a card the TCGPlayer feed can't price
export async function getEbayEstimate(cardId: string): Promise<EbayEstimate> {
  const res = await fetch(`${BASE}/cards/${encodeURIComponent(cardId)}/ebay-price`)
  if (!res.ok) throw new Error('Failed to fetch eBay estimate')
  return res.json()
}

export async function filterCards(filters: CardFilters, page = 1): Promise<CardPage> {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    // arrays become repeated params (?set_id=a&set_id=b) — the backend ORs them
    if (Array.isArray(value)) {
      for (const v of value) if (v) params.append(key, v)
    } else if (value) {
      params.set(key, value)
    }
  }
  params.set('page', String(page))
  const res = await fetch(`${BASE}/cards?${params}`)
  if (!res.ok) throw new Error('Search failed')
  return res.json()
}

// Camera scanner: upload a captured card image, get nearest-match candidates
// (same CardPage envelope the search endpoints return). Authed — /scan is
// login-only, so this goes through authedFetch (401 → SessionExpiredError).
export async function scanCard(blob: Blob): Promise<CardPage> {
  const form = new FormData()
  form.append('file', blob, 'scan.jpg')
  // No Content-Type header — the browser sets the multipart boundary itself.
  const res = await authedFetch('/scan', { method: 'POST', body: form })
  if (!res.ok) throw new Error('Scan failed')
  return res.json()
}

// ----- Portfolio calls (authed) ---------------------------------------------------

export async function getPortfolio(): Promise<PortfolioCard[]> {
  const res = await authedFetch('/portfolio')
  if (!res.ok) throw new Error('Failed to fetch portfolio')
  return res.json()
}

export async function getPortfolioHistory(): Promise<HistoryPoint[]> {
  const res = await authedFetch('/portfolio/history')
  if (!res.ok) throw new Error('Failed to fetch portfolio history')
  return res.json()
}

// purchase_price null = backend uses the current market price
// Returns the server message, e.g. "Card added" or "Merged — you now have 3"
export async function addCard(card_id: string, purchase_price: number | null, quantity: number): Promise<string> {
  const res = await authedFetch('/portfolio/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ card_id, purchase_price, quantity }),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || "We couldn't add that card. Please try again.")
  return data.message || 'Added to portfolio!'
}

// One item in a batch add: card_id, purchase_price (null = market price), quantity
export interface BatchAddItem {
  card_id: string
  purchase_price: number | null
  quantity: number
}

// Result of a batch add: how many landed, which items failed and why, and a message
export interface BatchAddResult {
  added: number
  failed: { card_id: string; reason: string }[]
  message: string
}

// Batch add for the scanner's batch mode: one request for a stack of scanned
// cards (up to 100). Reports per-item failures rather than failing the whole set.
export async function addCardBatch(items: BatchAddItem[]): Promise<BatchAddResult> {
  const res = await authedFetch('/portfolio/add-batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || "We couldn't add those cards. Please try again.")
  return data as BatchAddResult
}

export async function updateCard(id: number, updates: { purchase_price?: number; quantity?: number }): Promise<void> {
  const res = await authedFetch(`/portfolio/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  })
  if (!res.ok) {
    const data = await res.json()
    throw new Error(data.detail || 'Failed to update card')
  }
}

export async function removeCard(id: number): Promise<void> {
  const res = await authedFetch(`/portfolio/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to remove card')
}
