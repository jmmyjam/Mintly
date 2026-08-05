import { describe, it, expect, beforeEach, vi } from 'vitest'
import type { SetCompletion } from './api'
import { getOwnedSetCompletion, invalidateSetCompletion } from './setCompletion'
import { getSetCompletion, getToken } from './api'

vi.mock('./api', () => ({
  getToken: vi.fn(),
  getSetCompletion: vi.fn(),
}))

const mockToken = vi.mocked(getToken)
const mockCompletion = vi.mocked(getSetCompletion)

function sets(...ids: string[]): SetCompletion[] {
  return ids.map(set_id => ({ set_id, owned: 1, total: 10 })) as unknown as SetCompletion[]
}

beforeEach(() => {
  invalidateSetCompletion()
  mockToken.mockReturnValue('token')
  mockCompletion.mockResolvedValue([])
})

describe('getOwnedSetCompletion', () => {
  it('returns an empty list and skips the fetch when signed out', async () => {
    mockToken.mockReturnValue(null as unknown as string)
    const list = await getOwnedSetCompletion()
    expect(list).toEqual([])
    expect(mockCompletion).not.toHaveBeenCalled()
  })

  it('fetches account-wide completion (no portfolio id)', async () => {
    mockCompletion.mockResolvedValue(sets('base1'))
    await getOwnedSetCompletion()
    expect(mockCompletion).toHaveBeenCalledWith()
  })

  it('caches across calls (one fetch until invalidated)', async () => {
    mockCompletion.mockResolvedValue(sets('base1'))
    await getOwnedSetCompletion()
    await getOwnedSetCompletion()
    expect(mockCompletion).toHaveBeenCalledTimes(1)

    invalidateSetCompletion()
    await getOwnedSetCompletion()
    expect(mockCompletion).toHaveBeenCalledTimes(2)
  })

  it('shares one in-flight request between concurrent callers', async () => {
    mockCompletion.mockResolvedValue(sets('base1'))
    const [first, second] = await Promise.all([getOwnedSetCompletion(), getOwnedSetCompletion()])
    expect(mockCompletion).toHaveBeenCalledTimes(1)
    expect(first).toBe(second)
  })

  it('resolves to an empty list when the fetch fails', async () => {
    mockCompletion.mockRejectedValue(new Error('network'))
    const list = await getOwnedSetCompletion()
    expect(list).toEqual([])
  })
})
