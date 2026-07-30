import { describe, it, expect } from 'vitest'
import {
  groupByCard,
  groupMetrics,
  parseUTCDate,
  localISODate,
  lotISODate,
  formatLotDate,
  formatChartDate,
  type CardGroup,
} from './portfolio'
import type { PortfolioCard } from './api'

// These date helpers format in local time; the test scripts pin TZ=UTC (see
// package.json) so the expected strings below are deterministic.

let nextId = 1
function lot(overrides: Partial<PortfolioCard> = {}): PortfolioCard {
  return {
    id: nextId++,
    card_id: 'base1-4',
    card_name: 'Charizard',
    quantity: 1,
    purchase_price: 10,
    purchase_date: '2026-07-10T00:00:00',
    current_price: 15,
    gain_loss: 5,
    gain_loss_pct: 50,
    price_change: null,
    image_url: null,
    ...overrides,
  }
}

function groupOf(lots: PortfolioCard[]): CardGroup {
  return groupByCard(lots)[0]
}

describe('groupByCard', () => {
  it('groups lots of the same card into one entry', () => {
    const groups = groupByCard([
      lot({ card_id: 'a' }),
      lot({ card_id: 'a' }),
      lot({ card_id: 'b' }),
    ])
    expect(groups).toHaveLength(2)
    expect(groups[0].card_id).toBe('a')
    expect(groups[0].lots).toHaveLength(2)
    expect(groups[1].card_id).toBe('b')
    expect(groups[1].lots).toHaveLength(1)
  })

  it('takes the group price/image from the first lot seen', () => {
    const groups = groupByCard([
      lot({ card_id: 'a', current_price: 15, image_url: 'first.png' }),
      lot({ card_id: 'a', current_price: 99, image_url: 'second.png' }),
    ])
    expect(groups[0].current_price).toBe(15)
    expect(groups[0].image_url).toBe('first.png')
  })
})

describe('groupMetrics', () => {
  it('sums quantity/cost, averages the paid price, and totals value + gain', () => {
    const group = groupOf([
      lot({ quantity: 2, purchase_price: 10, current_price: 15, gain_loss: 10, purchase_date: '2026-07-10T00:00:00' }),
      lot({ quantity: 1, purchase_price: 20, current_price: 15, gain_loss: -5, purchase_date: '2026-07-15T00:00:00' }),
    ])
    const m = groupMetrics(group)
    expect(m.qty).toBe(3)
    expect(m.cost).toBe(40)
    expect(m.avg).toBeCloseTo(13.333, 3)
    expect(m.value).toBe(45)
    expect(m.gain).toBe(5)
    expect(m.gainPct).toBe(12.5)
    expect(m.minPaid).toBe(10)
    expect(m.maxPaid).toBe(20)
  })

  it('reports gain/gainPct as null when the card has no market price', () => {
    const group = groupOf([lot({ current_price: null, gain_loss: null })])
    // groupByCard read current_price from the (null-priced) first lot
    const m = groupMetrics(group)
    expect(m.market).toBeNull()
    expect(m.gain).toBeNull()
    expect(m.gainPct).toBeNull()
  })

  it('falls back to purchase price for value when a lot is unpriced', () => {
    const group = groupOf([lot({ quantity: 2, purchase_price: 12, current_price: null })])
    const m = groupMetrics(group)
    expect(m.value).toBe(24) // 12 * 2, since current_price is null
  })

  it('computes the whole-holding day change as per-unit change x quantity', () => {
    const group = groupOf([
      lot({ quantity: 3, price_change: { amount: 0.5, percent: 2, since: '2026-07-20' } }),
    ])
    expect(groupMetrics(group).dayChange).toBe(1.5)
  })

  it('leaves day change null when there is no price_change', () => {
    const group = groupOf([lot({ price_change: null })])
    expect(groupMetrics(group).dayChange).toBeNull()
  })

  it('tracks newest and oldest purchase timestamps', () => {
    const group = groupOf([
      lot({ purchase_date: '2026-07-10T00:00:00' }),
      lot({ purchase_date: '2026-07-15T00:00:00' }),
    ])
    const m = groupMetrics(group)
    expect(m.firstAdded).toBe(Date.parse('2026-07-10T00:00:00Z'))
    expect(m.added).toBe(Date.parse('2026-07-15T00:00:00Z'))
  })
})

describe('date helpers', () => {
  it('parseUTCDate anchors a naive timestamp to UTC', () => {
    expect(parseUTCDate('2026-07-10T00:00:00').getTime()).toBe(Date.parse('2026-07-10T00:00:00Z'))
  })

  it('parseUTCDate leaves an already-zoned timestamp alone', () => {
    expect(parseUTCDate('2026-07-10T00:00:00Z').getTime()).toBe(Date.parse('2026-07-10T00:00:00Z'))
  })

  it('localISODate renders YYYY-MM-DD with zero padding', () => {
    expect(localISODate(new Date('2026-03-05T00:00:00Z'))).toBe('2026-03-05')
  })

  it('lotISODate maps a naive-UTC purchase to its calendar day', () => {
    expect(lotISODate('2026-07-10T00:00:00')).toBe('2026-07-10')
  })

  it('formatLotDate renders a full human date', () => {
    expect(formatLotDate('2026-07-10T00:00:00')).toBe('Jul 10, 2026')
  })

  it('formatChartDate renders a short month/day axis label', () => {
    expect(formatChartDate('2026-07-10')).toBe('Jul 10')
  })
})
