import { describe, it, expect } from 'vitest'
import { money, signedMoney } from './format'

describe('money', () => {
  it('formats a value with a $ and two decimals', () => {
    expect(money(12.5)).toBe('$12.50')
  })

  it('separates thousands', () => {
    expect(money(1234.56)).toBe('$1,234.56')
    expect(money(1000000)).toBe('$1,000,000.00')
  })

  it('rounds to two decimals', () => {
    expect(money(0.005)).toBe('$0.01')
  })

  it('shows an em dash for null/undefined, not $0.00', () => {
    expect(money(null)).toBe('—')
    expect(money(undefined)).toBe('—')
  })

  it('treats a real zero as a value, not missing', () => {
    expect(money(0)).toBe('$0.00')
  })
})

describe('signedMoney', () => {
  it('puts a + before the $ for gains', () => {
    expect(signedMoney(6.31)).toBe('+$6.31')
  })

  it('puts a - before the $ for losses (sign, then dollar, then magnitude)', () => {
    expect(signedMoney(-58.11)).toBe('-$58.11')
  })

  it('shows no sign for exactly zero', () => {
    expect(signedMoney(0)).toBe('$0.00')
  })

  it('separates thousands and keeps two decimals', () => {
    expect(signedMoney(-1234.5)).toBe('-$1,234.50')
  })
})
