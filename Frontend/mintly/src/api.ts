const BASE = 'http://localhost:8000'

export interface PriceVariant {
  low?: number
  mid?: number
  high?: number
  market?: number
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
}

export function getToken() {
  return localStorage.getItem('token')
}

export function setToken(token: string) {
  localStorage.setItem('token', token)
}

export function clearToken() {
  localStorage.removeItem('token')
}

// Adds the auth header; a 401 means the token is expired/invalid, so clear it
async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { ...(init.headers || {}), Authorization: `Bearer ${getToken()}` },
  })
  if (res.status === 401) {
    clearToken()
    throw new Error('Session expired — please log in again.')
  }
  return res
}

export function getCardImageUrl(cardId: string): string {
  const [setId, number] = cardId.split('-')
  return `https://images.pokemontcg.io/${setId}/${number}.png`
}

export function getCardPrice(card: Card): number | null {
  const prices = card.tcgplayer?.prices
  if (!prices) return null
  for (const type of ['holofoil', 'normal', 'reverseHolofoil', '1stEditionHolofoil']) {
    const mid = prices[type]?.mid
    if (mid != null) return mid
  }
  return null
}

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

export async function register(email: string, username: string, password: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/register?${new URLSearchParams({ email, username, password })}`, {
    method: 'POST',
  })
  if (!res.ok) {
    const data = await res.json()
    throw new Error(data.detail || 'Registration failed')
  }
}

export async function searchCards(query: string): Promise<Card[]> {
  const res = await fetch(`${BASE}/search?q=${encodeURIComponent(query)}`)
  if (!res.ok) throw new Error('Search failed')
  return res.json()
}

export interface CardSet {
  id: string
  name: string
  series: string
  releaseDate: string
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

export interface CardFilters {
  name?: string
  set_id?: string
  number?: string
  rarity?: string
  type?: string
}

export async function filterCards(filters: CardFilters): Promise<Card[]> {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value)
  }
  const res = await fetch(`${BASE}/cards?${params}`)
  if (!res.ok) throw new Error('Search failed')
  return res.json()
}

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
