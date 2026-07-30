import { describe, it, expect, beforeEach, vi } from 'vitest'
import type { PortfolioCard } from './api'
import { getOwnedQty, invalidateOwned } from './owned'
import { getPortfolio, getToken } from './api'

vi.mock('./api', () => ({
  getToken: vi.fn(),
  getPortfolio: vi.fn(),
}))

const mockToken = vi.mocked(getToken)
const mockPortfolio = vi.mocked(getPortfolio)

function lots(...entries: [string, number][]): PortfolioCard[] {
  return entries.map(([card_id, quantity]) => ({ card_id, quantity })) as unknown as PortfolioCard[]
}

beforeEach(() => {
  invalidateOwned()
  mockToken.mockReturnValue('token')
  mockPortfolio.mockResolvedValue([])
})

describe('getOwnedQty', () => {
  it('returns an empty map and skips the fetch when signed out', async () => {
    mockToken.mockReturnValue(null as unknown as string)
    const map = await getOwnedQty()
    expect(map.size).toBe(0)
    expect(mockPortfolio).not.toHaveBeenCalled()
  })

  it('aggregates total quantity per card_id across lots', async () => {
    mockPortfolio.mockResolvedValue(lots(['a', 2], ['a', 3], ['b', 1]))
    const map = await getOwnedQty()
    expect(map.get('a')).toBe(5)
    expect(map.get('b')).toBe(1)
  })

  it('caches across calls (one fetch until invalidated)', async () => {
    mockPortfolio.mockResolvedValue(lots(['a', 1]))
    await getOwnedQty()
    await getOwnedQty()
    expect(mockPortfolio).toHaveBeenCalledTimes(1)

    invalidateOwned()
    await getOwnedQty()
    expect(mockPortfolio).toHaveBeenCalledTimes(2)
  })

  it('shares one in-flight request between concurrent callers', async () => {
    mockPortfolio.mockResolvedValue(lots(['a', 1]))
    const [first, second] = await Promise.all([getOwnedQty(), getOwnedQty()])
    expect(mockPortfolio).toHaveBeenCalledTimes(1)
    expect(first).toBe(second)
  })

  it('resolves to an empty map when the portfolio fetch fails', async () => {
    mockPortfolio.mockRejectedValue(new Error('network'))
    const map = await getOwnedQty()
    expect(map.size).toBe(0)
  })
})
