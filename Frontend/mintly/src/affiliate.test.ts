import { describe, it, expect } from 'vitest'
import {
  tcgplayerSearchUrl,
  tcgplayerBuyLink,
  ebaySearchUrl,
  ebayBuyLink,
} from './affiliate'
import type { Card } from './api'

// These tests exercise the default (env-unset) behavior: no Impact link and no
// EPN campaign id are configured under test, so every builder returns a plain,
// non-affiliate link. That's the pre-approval production behavior too.

// eBay's search keyword lives in the _nkw param; read it back rather than
// asserting brittle percent-encoding.
function ebayKeyword(url: string): string {
  return new URL(url).searchParams.get('_nkw') ?? ''
}

describe('tcgplayerSearchUrl', () => {
  it('builds a pokemon product search from name + number', () => {
    const url = new URL(tcgplayerSearchUrl({ name: 'Charizard', number: '4' }))
    expect(url.pathname).toBe('/search/pokemon/product')
    expect(url.searchParams.get('productLineName')).toBe('pokemon')
    expect(url.searchParams.get('q')).toBe('Charizard 4')
  })

  it('omits a missing number cleanly', () => {
    const url = new URL(tcgplayerSearchUrl({ name: 'Charizard', number: undefined }))
    expect(url.searchParams.get('q')).toBe('Charizard')
  })
})

describe('ebaySearchUrl', () => {
  it('appends the set printedTotal to a plain-digit number (4/102)', () => {
    const url = ebaySearchUrl({
      name: 'Charizard',
      number: '4',
      set: { name: 'Base', id: 'base1', printedTotal: 102 },
    })
    expect(ebayKeyword(url)).toBe('Charizard 4/102')
  })

  it('leaves a lettered number bare (TG12)', () => {
    const url = ebaySearchUrl({
      name: 'Rayquaza',
      number: 'TG12',
      set: { name: 'Lost Origin', id: 'swsh11', printedTotal: 196 },
    })
    expect(ebayKeyword(url)).toBe('Rayquaza TG12')
  })

  it('uses the set name for a numberless card', () => {
    const url = ebaySearchUrl({
      name: 'Pikachu',
      number: '',
      set: { name: 'Detective Pikachu', id: 'det1' },
    })
    expect(ebayKeyword(url)).toBe('Pikachu Detective Pikachu')
  })

  it('does not append attribution params when no campaign id is configured', () => {
    const url = new URL(
      ebaySearchUrl({ name: 'Charizard', number: '4', set: { name: 'Base', id: 'base1', printedTotal: 102 } }),
    )
    expect(url.searchParams.get('campid')).toBeNull()
    expect(url.searchParams.get('mkcid')).toBeNull()
  })
})

describe('ebayBuyLink', () => {
  it('reports affiliate=false with no campaign id configured', () => {
    const link = ebayBuyLink({ name: 'Charizard', number: '4', set: { name: 'Base', id: 'base1' } })
    expect(link.affiliate).toBe(false)
    expect(link.href).toContain('ebay.com/sch/i.html')
  })
})

describe('tcgplayerBuyLink', () => {
  const card = (overrides: Partial<Card>): Card =>
    ({ name: 'Charizard', number: '4', ...overrides } as Card)

  it('uses the stored TCGplayer url when present, un-wrapped (no Impact link set)', () => {
    const link = tcgplayerBuyLink(card({ tcgplayer: { url: 'https://www.tcgplayer.com/product/42' } }))
    expect(link.href).toBe('https://www.tcgplayer.com/product/42')
    expect(link.affiliate).toBe(false)
  })

  it('falls back to a name+number search when the card has no stored url', () => {
    const link = tcgplayerBuyLink(card({ tcgplayer: undefined }))
    expect(link.affiliate).toBe(false)
    const url = new URL(link.href)
    expect(url.pathname).toBe('/search/pokemon/product')
    expect(url.searchParams.get('q')).toBe('Charizard 4')
  })
})
