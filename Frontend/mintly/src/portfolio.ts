// Shared portfolio math + date helpers, used by both the Portfolio grid and the
// per-card Holding route (/portfolio/:cardId), so the two pages compute a card's
// quantity, cost basis, average paid, value and P&L exactly the same way.

import type { PortfolioCard, PriceChange } from './api'

// One card can have several lots — separate purchases at different prices.
export interface CardGroup {
  card_id: string
  card_name: string
  current_price: number | null
  price_change: PriceChange | null
  image_url: string | null
  lots: PortfolioCard[]
}

// ----- Date helpers ----------------------------------------------------------

// purchase_date arrives as naive UTC with no zone suffix; anchor it with Z so
// it converts to the local date instead of being read as local time.
export function parseUTCDate(d: string): Date {
  return new Date(d.endsWith('Z') ? d : d + 'Z')
}

export function localISODate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// The local calendar day a purchase falls on, as YYYY-MM-DD (for chart markers)
export function lotISODate(d: string): string {
  return localISODate(parseUTCDate(d))
}

export function formatLotDate(d: string): string {
  return parseUTCDate(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// A "Jul 17" chart-axis label from a YYYY-MM-DD string (already a calendar date)
export function formatChartDate(d: string): string {
  return new Date(d + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// ----- Grouping + metrics ----------------------------------------------------

export function groupByCard(cards: PortfolioCard[]): CardGroup[] {
  const map = new Map<string, CardGroup>()
  for (const c of cards) {
    const group = map.get(c.card_id)
    if (group) {
      group.lots.push(c)
    } else {
      map.set(c.card_id, {
        card_id: c.card_id,
        card_name: c.card_name,
        current_price: c.current_price,
        price_change: c.price_change,
        image_url: c.image_url,
        lots: [c],
      })
    }
  }
  return [...map.values()]
}

function round2(n: number): number {
  return Math.round(n * 100) / 100
}

export interface GroupMetrics {
  qty: number
  cost: number
  avg: number
  market: number | null
  value: number
  // gain is null when the card has no market price (it can't be a gainer/loser)
  gain: number | null
  gainPct: number | null
  minPaid: number
  maxPaid: number
  // today's move across the whole holding: per-unit day change × quantity
  dayChange: number | null
  // newest / oldest purchase timestamps (ms), for sorting + "since" copy
  added: number
  firstAdded: number
}

// Everything the grid tile and the holding page derive from a card's lots.
export function groupMetrics(g: CardGroup): GroupMetrics {
  const lots = g.lots
  const qty = lots.reduce((s, l) => s + l.quantity, 0)
  const cost = lots.reduce((s, l) => s + l.purchase_price * l.quantity, 0)
  const avg = qty > 0 ? cost / qty : 0
  const value = lots.reduce((s, l) => s + (l.current_price ?? l.purchase_price) * l.quantity, 0)
  const gain = g.current_price != null ? lots.reduce((s, l) => s + (l.gain_loss ?? 0), 0) : null
  const gainPct = gain != null && cost > 0 ? round2((gain / cost) * 100) : null
  const paid = lots.map(l => l.purchase_price)
  const times = lots.map(l => parseUTCDate(l.purchase_date).getTime() || 0)
  return {
    qty,
    cost,
    avg,
    market: g.current_price,
    value,
    gain,
    gainPct,
    minPaid: Math.min(...paid),
    maxPaid: Math.max(...paid),
    dayChange: g.price_change ? round2(g.price_change.amount * qty) : null,
    added: Math.max(...times),
    firstAdded: Math.min(...times),
  }
}
