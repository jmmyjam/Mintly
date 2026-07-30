import { describe, it, expect } from 'vitest'
import {
  PRICE_PREFERENCE,
  variantLabel,
  variantShortLabel,
  variantColor,
  sortVariants,
  mergeHeadline,
} from './variants'
import type { PricePoint } from './api'

describe('variantLabel / variantShortLabel', () => {
  it('maps known variant keys to their display labels', () => {
    expect(variantLabel('reverseHolofoil')).toBe('Reverse Holofoil')
    expect(variantShortLabel('reverseHolofoil')).toBe('Reverse')
    expect(variantShortLabel('1stEditionHolofoil')).toBe('1st Ed Holo')
  })

  it('falls back to the raw key for unknown variants', () => {
    expect(variantLabel('mysteryFoil')).toBe('mysteryFoil')
    expect(variantShortLabel('mysteryFoil')).toBe('mysteryFoil')
  })
})

describe('variantColor', () => {
  it('gives each known variant its fixed color', () => {
    expect(variantColor('holofoil')).toBe('#3987e5')
    expect(variantColor('normal')).toBe('#008300')
  })

  it('returns the neutral fallback for an unknown variant', () => {
    expect(variantColor('somethingElse')).toBe('#9c9ca4')
  })
})

describe('sortVariants', () => {
  it('orders by the price-preference order first', () => {
    const sorted = sortVariants(['reverseHolofoil', 'normal', 'holofoil'])
    expect(sorted).toEqual(['holofoil', 'normal', 'reverseHolofoil'])
  })

  it('puts unknown keys after known ones, alphabetically', () => {
    const sorted = sortVariants(['zeta', 'holofoil', 'alpha'])
    expect(sorted).toEqual(['holofoil', 'alpha', 'zeta'])
  })

  it('does not mutate its input', () => {
    const input = ['normal', 'holofoil']
    sortVariants(input)
    expect(input).toEqual(['normal', 'holofoil'])
  })

  it('keeps the documented preference order stable', () => {
    expect(PRICE_PREFERENCE).toEqual([
      'holofoil',
      'normal',
      'reverseHolofoil',
      '1stEditionHolofoil',
    ])
  })
})

describe('mergeHeadline', () => {
  const pt = (date: string, price: number): PricePoint => ({ date, price })

  it('backfills the preferred variant with earlier headline points', () => {
    const points = [pt('2026-01-01', 5), pt('2026-01-02', 6), pt('2026-01-03', 7)]
    const variants = { holofoil: [pt('2026-01-03', 7), pt('2026-01-04', 8)] }
    const merged = mergeHeadline(points, variants)
    expect(merged.holofoil).toEqual([
      pt('2026-01-01', 5),
      pt('2026-01-02', 6),
      pt('2026-01-03', 7),
      pt('2026-01-04', 8),
    ])
  })

  it('is a no-op when there are no headline points', () => {
    const variants = { holofoil: [pt('2026-01-03', 7)] }
    expect(mergeHeadline([], variants)).toBe(variants)
  })

  it('is a no-op when there are no variants', () => {
    const points = [pt('2026-01-01', 5)]
    expect(mergeHeadline(points, {})).toEqual({})
  })

  it('adds nothing when every headline point is already covered', () => {
    const points = [pt('2026-01-03', 7)]
    const variants = { holofoil: [pt('2026-01-01', 5), pt('2026-01-03', 7)] }
    expect(mergeHeadline(points, variants)).toBe(variants)
  })

  it('backfills against the preferred variant even when others sort first alphabetically', () => {
    const points = [pt('2026-01-01', 1)]
    const variants = {
      normal: [pt('2026-01-02', 2)],
      holofoil: [pt('2026-01-02', 3)], // holofoil is preferred over normal
    }
    const merged = mergeHeadline(points, variants)
    expect(merged.holofoil[0]).toEqual(pt('2026-01-01', 1))
    expect(merged.normal).toEqual([pt('2026-01-02', 2)])
  })
})
