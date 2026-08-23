import { describe, it, expect, vi, beforeEach } from 'vitest'
import { clearAccountCaches } from './session'
import { clearPortfolios } from './portfolios'
import { invalidateOwned } from './owned'
import { invalidateSetCompletion } from './setCompletion'

// The helper exists so no identity-change site can drop only *some* per-account
// caches (the bug it fixes: logout/login left owned + set-completion behind, and
// OAuthCallback cleared owned but forgot set-completion). Guard that it clears
// all three together.
vi.mock('./portfolios', () => ({ clearPortfolios: vi.fn() }))
vi.mock('./owned', () => ({ invalidateOwned: vi.fn() }))
vi.mock('./setCompletion', () => ({ invalidateSetCompletion: vi.fn() }))

describe('clearAccountCaches', () => {
  beforeEach(() => vi.clearAllMocks())

  it('drops the portfolios, owned, and set-completion caches together', () => {
    clearAccountCaches()
    expect(clearPortfolios).toHaveBeenCalledTimes(1)
    expect(invalidateOwned).toHaveBeenCalledTimes(1)
    expect(invalidateSetCompletion).toHaveBeenCalledTimes(1)
  })
})
