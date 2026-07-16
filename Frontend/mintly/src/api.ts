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
}

// One daily point in a card's price history (from Mintly's own snapshots)
export interface PricePoint {
  date: string
  price: number
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
  set_id?: string
  number?: string
  rarity?: string
  type?: string
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

// Thrown on 401 so pages can redirect to /login instead of showing a generic error
export class SessionExpiredError extends Error {
  constructor() {
    super('Session expired — please log in again.')
    this.name = 'SessionExpiredError'
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

export function getCardImageUrl(cardId: string): string {
  const [setId, number] = cardId.split('-')
  return `https://images.pokemontcg.io/${setId}/${number}.png`
}

// Keep in sync with extract_price in Backend/app/services/price_history.py: market, then mid
export function getCardPrice(card: Card): number | null {
  const prices = card.tcgplayer?.prices
  if (!prices) return null
  for (const type of ['holofoil', 'normal', 'reverseHolofoil', '1stEditionHolofoil']) {
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
  if (!res.ok) throw new Error('Invalid credentials')
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
    throw new Error(data.detail || 'Registration failed')
  }
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
export async function getCardHistory(cardId: string, days = 1825): Promise<PricePoint[]> {
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
    if (value) params.set(key, value)
  }
  params.set('page', String(page))
  const res = await fetch(`${BASE}/cards?${params}`)
  if (!res.ok) throw new Error('Search failed')
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
  if (!res.ok) throw new Error(data.detail || 'Failed to add card')
  return data.message || 'Added to portfolio!'
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
