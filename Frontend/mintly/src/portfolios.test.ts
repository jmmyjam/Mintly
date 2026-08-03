import { describe, it, expect, beforeEach, vi } from 'vitest'
import type { Portfolio } from './api'
import { refreshPortfolios, setActivePortfolio, clearPortfolios } from './portfolios'
import { getPortfolios, getToken } from './api'

vi.mock('./api', () => ({
  getToken: vi.fn(),
  getPortfolios: vi.fn(),
}))

const mockToken = vi.mocked(getToken)
const mockList = vi.mocked(getPortfolios)

function pf(id: number, is_default = false): Portfolio {
  return { id, name: `P${id}`, is_default, created_at: '', card_count: 0 }
}

const KEY = 'mintly.activePortfolio'

beforeEach(() => {
  localStorage.clear()
  clearPortfolios()
  mockToken.mockReturnValue('token')
  mockList.mockResolvedValue([])
})

describe('portfolios store', () => {
  it('skips the fetch and resolves when signed out', async () => {
    mockToken.mockReturnValue(null as unknown as string)
    await refreshPortfolios()
    expect(mockList).not.toHaveBeenCalled()
  })

  it('defaults the active id to the default portfolio on first load', async () => {
    mockList.mockResolvedValue([pf(1), pf(2, true)])
    await refreshPortfolios()
    expect(localStorage.getItem(KEY)).toBe('2')
  })

  it('keeps a remembered active id when it still exists', async () => {
    setActivePortfolio(1)
    mockList.mockResolvedValue([pf(1), pf(2, true)])
    await refreshPortfolios()
    expect(localStorage.getItem(KEY)).toBe('1')
  })

  it('falls back to the default when the remembered id is gone', async () => {
    setActivePortfolio(99)
    mockList.mockResolvedValue([pf(1), pf(2, true)])
    await refreshPortfolios()
    expect(localStorage.getItem(KEY)).toBe('2')
  })

  it('setActivePortfolio persists the selection', () => {
    setActivePortfolio(5)
    expect(localStorage.getItem(KEY)).toBe('5')
  })

  it('clearPortfolios removes the stored selection', () => {
    setActivePortfolio(5)
    clearPortfolios()
    expect(localStorage.getItem(KEY)).toBeNull()
  })
})
