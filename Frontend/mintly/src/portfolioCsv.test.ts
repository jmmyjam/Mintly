import { describe, it, expect } from 'vitest'
import { toPortfolioCsv, parsePortfolioCsv } from './portfolioCsv'
import type { PortfolioCard } from './api'

function lot(over: Partial<PortfolioCard> = {}): PortfolioCard {
  return {
    id: 1,
    card_id: 'base1-4',
    card_name: 'Charizard',
    quantity: 2,
    purchase_price: 350,
    purchase_date: '2021-03-04T00:00:00',
    current_price: 500,
    gain_loss: 300,
    gain_loss_pct: 42.86,
    price_change: null,
    image_url: null,
    ...over,
  }
}

describe('toPortfolioCsv', () => {
  it('writes a header and one row per lot with raw numbers', () => {
    const csv = toPortfolioCsv([lot()])
    const [header, row] = csv.split('\r\n')
    expect(header.split(',')[0]).toBe('card_id')
    expect(row).toContain('base1-4')
    expect(row).toContain('350') // no $ or thousands separators
  })

  it('computes market_value and cost_basis from quantity', () => {
    const csv = toPortfolioCsv([lot({ quantity: 2, purchase_price: 350, current_price: 500 })])
    const cells = csv.split('\r\n')[1].split(',')
    // columns: ...current_price, market_value, cost_basis...
    expect(cells).toContain('1000') // market value 500 * 2
    expect(cells).toContain('700') // cost basis 350 * 2
  })

  it('leaves priceless columns blank rather than writing 0', () => {
    const csv = toPortfolioCsv([lot({ current_price: null, gain_loss: null, gain_loss_pct: null })])
    const cells = csv.split('\r\n')[1].split(',')
    expect(cells[5]).toBe('') // current_price
    expect(cells[6]).toBe('') // market_value
  })

  it('quotes a name containing a comma', () => {
    const csv = toPortfolioCsv([lot({ card_name: 'Farfetch, d' })])
    expect(csv.split('\r\n')[1]).toContain('"Farfetch, d"')
  })

  it('neutralizes a formula-injection name', () => {
    const csv = toPortfolioCsv([lot({ card_name: '=SUM(A1)' })])
    expect(csv.split('\r\n')[1]).toContain("'=SUM(A1)")
  })
})

describe('parsePortfolioCsv', () => {
  it('round-trips an exported file back to matching items', () => {
    const cards = [
      lot({ card_id: 'base1-4', purchase_price: 350, quantity: 2, purchase_date: '2021-03-04T00:00:00' }),
      lot({ id: 2, card_id: 'sv3pt5-199', purchase_price: 12.5, quantity: 1, purchase_date: '2022-06-01T00:00:00' }),
    ]
    const { items, skipped, total } = parsePortfolioCsv(toPortfolioCsv(cards))
    expect(skipped).toBe(0)
    expect(total).toBe(2)
    expect(items).toEqual([
      { card_id: 'base1-4', purchase_price: 350, quantity: 2, purchase_date: '2021-03-04T00:00:00' },
      { card_id: 'sv3pt5-199', purchase_price: 12.5, quantity: 1, purchase_date: '2022-06-01T00:00:00' },
    ])
  })

  it('recovers the name across a quoted comma without shifting columns', () => {
    const items = parsePortfolioCsv(toPortfolioCsv([lot({ card_name: 'Farfetch, d', card_id: 'x-1' })])).items
    expect(items[0].card_id).toBe('x-1')
  })

  it('accepts a minimal hand-made file (card_id + price + quantity header)', () => {
    const { items } = parsePortfolioCsv('card_id,purchase_price,quantity\nsv3pt5-199,10,3')
    expect(items).toEqual([{ card_id: 'sv3pt5-199', purchase_price: 10, quantity: 3, purchase_date: null }])
  })

  it('falls back to positional order when there is no recognizable header', () => {
    const { items } = parsePortfolioCsv('sv3pt5-199,10,3')
    expect(items[0]).toMatchObject({ card_id: 'sv3pt5-199', purchase_price: 10, quantity: 3 })
  })

  it('treats a blank price as null (market) and blank/invalid quantity as 1', () => {
    const { items } = parsePortfolioCsv('card_id,purchase_price,quantity\nbase1-4,,\nbase1-2,5,0')
    expect(items[0]).toMatchObject({ card_id: 'base1-4', purchase_price: null, quantity: 1 })
    expect(items[1]).toMatchObject({ card_id: 'base1-2', purchase_price: 5, quantity: 1 }) // qty 0 -> 1
  })

  it('forgives a $ and thousands separators in the price', () => {
    const { items } = parsePortfolioCsv('card_id,purchase_price\nbase1-4,"$1,234.50"')
    expect(items[0].purchase_price).toBe(1234.5)
  })

  it('skips and counts rows missing a card_id', () => {
    const { items, skipped, total } = parsePortfolioCsv('card_id,purchase_price\nbase1-4,10\n,99\nbase1-2,20')
    expect(items.map(i => i.card_id)).toEqual(['base1-4', 'base1-2'])
    expect(skipped).toBe(1)
    expect(total).toBe(3)
  })

  it('ignores blank lines and a trailing newline', () => {
    const { items, total } = parsePortfolioCsv('card_id,purchase_price\n\nbase1-4,10\n')
    expect(items).toHaveLength(1)
    expect(total).toBe(1)
  })

  it('is case-insensitive about header names', () => {
    const { items } = parsePortfolioCsv('Card_ID,Purchase_Price\nbase1-4,10')
    expect(items[0]).toMatchObject({ card_id: 'base1-4', purchase_price: 10 })
  })

  it('returns nothing for an empty string', () => {
    expect(parsePortfolioCsv('')).toEqual({ items: [], skipped: 0, total: 0 })
  })
})
