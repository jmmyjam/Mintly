const BASE = 'http://localhost:8000'

export interface Card {
  id: string
  name: string
  images: { small: string; large: string }
  set: { name: string; id: string }
  tcgplayer?: {
    prices?: { [key: string]: { mid?: number } }
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

export async function getPortfolio(): Promise<PortfolioCard[]> {
  const res = await fetch(`${BASE}/portfolio`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  if (!res.ok) throw new Error('Failed to fetch portfolio')
  return res.json()
}

export async function getPortfolioHistory(): Promise<HistoryPoint[]> {
  const res = await fetch(`${BASE}/portfolio/history`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  if (!res.ok) throw new Error('Failed to fetch portfolio history')
  return res.json()
}

// purchase_price null = backend uses the current market price
export async function addCard(card_id: string, purchase_price: number | null, quantity: number): Promise<void> {
  const res = await fetch(`${BASE}/portfolio/add`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${getToken()}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ card_id, purchase_price, quantity }),
  })
  if (!res.ok) {
    const data = await res.json()
    throw new Error(data.detail || 'Failed to add card')
  }
}

export async function removeCard(id: number): Promise<void> {
  const res = await fetch(`${BASE}/portfolio/${id}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  if (!res.ok) throw new Error('Failed to remove card')
}
