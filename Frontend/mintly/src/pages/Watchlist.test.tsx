import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Watchlist from './Watchlist'
import {
  getWatchlist, updateWatchlistItem, removeFromWatchlist, getToken,
  type WatchlistItem,
} from '../api'
import { axe, renderWithRouter } from '../test/utils'

// Mock only the network fns; keep the pure helpers/error classes real via the
// importActual spread so the page renders exactly as in production.
vi.mock('../api', async (importActual) => {
  const actual = await importActual<typeof import('../api')>()
  return {
    ...actual,
    getWatchlist: vi.fn(),
    updateWatchlistItem: vi.fn(),
    removeFromWatchlist: vi.fn(),
    getToken: vi.fn(),
  }
})

const mockGetWatchlist = vi.mocked(getWatchlist)
const mockUpdate = vi.mocked(updateWatchlistItem)
const mockRemove = vi.mocked(removeFromWatchlist)
const mockToken = vi.mocked(getToken)

function watch(over: Partial<WatchlistItem> & { id: number; card_id: string; card_name: string }): WatchlistItem {
  return {
    target_price: null,
    direction: 'below',
    created_at: '2026-08-01T00:00:00',
    current_price: 100,
    price_change: null,
    image_url: null,
    triggered: false,
    ...over,
  }
}

beforeEach(() => {
  localStorage.clear()
  mockToken.mockReturnValue('a-token')
  mockGetWatchlist.mockResolvedValue([])
  mockUpdate.mockResolvedValue()
  mockRemove.mockResolvedValue()
})

describe('Watchlist', () => {
  it('prompts to log in when signed out', async () => {
    mockToken.mockReturnValue(null)
    const { container } = renderWithRouter(<Watchlist />, { route: '/watchlist' })
    expect(await screen.findByText(/log in to build a watchlist/i)).toBeInTheDocument()
    expect(mockGetWatchlist).not.toHaveBeenCalled()
    expect(await axe(container)).toHaveNoViolations()
  })

  it('shows an empty state with no watched cards', async () => {
    const { container } = renderWithRouter(<Watchlist />, { route: '/watchlist' })
    expect(await screen.findByText(/your watchlist is empty/i)).toBeInTheDocument()
    expect(await axe(container)).toHaveNoViolations()
  })

  it('lists watched cards with price and alert config', async () => {
    mockGetWatchlist.mockResolvedValue([
      watch({ id: 1, card_id: 'base1-4', card_name: 'Charizard', current_price: 95,
              target_price: 100, direction: 'below', triggered: true }),
      watch({ id: 2, card_id: 'base1-2', card_name: 'Blastoise', target_price: null }),
    ])
    const { container } = renderWithRouter(<Watchlist />, { route: '/watchlist' })

    const charizard = (await screen.findByText('Charizard')).closest('li')!
    // triggered alert reads "Target hit: below $100.00"
    expect(within(charizard).getByText(/target hit/i)).toBeInTheDocument()
    expect(within(charizard).getByText(/\$100\.00/)).toBeInTheDocument()

    const blastoise = screen.getByText('Blastoise').closest('li')!
    expect(within(blastoise).getByText(/no price alert/i)).toBeInTheDocument()
    expect(await axe(container)).toHaveNoViolations()
  })

  it('edits a target price and saves', async () => {
    const user = userEvent.setup()
    mockGetWatchlist.mockResolvedValue([
      watch({ id: 7, card_id: 'base1-4', card_name: 'Charizard', target_price: 100 }),
    ])
    renderWithRouter(<Watchlist />, { route: '/watchlist' })

    await user.click(await screen.findByRole('button', { name: /edit/i }))
    const input = screen.getByLabelText(/target price/i)
    await user.clear(input)
    await user.type(input, '80')
    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith(7, 80, 'below'))
    // reload is fired after a successful save
    expect(mockGetWatchlist).toHaveBeenCalledTimes(2)
  })

  it('removes a card after confirming', async () => {
    const user = userEvent.setup()
    mockGetWatchlist.mockResolvedValue([
      watch({ id: 9, card_id: 'base1-4', card_name: 'Charizard', target_price: 100 }),
    ])
    renderWithRouter(<Watchlist />, { route: '/watchlist' })

    await user.click(await screen.findByRole('button', { name: /^remove$/i }))
    // two-step: a confirm "Remove" appears alongside "Keep"
    expect(screen.getByText(/remove from watchlist\?/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /keep/i }))
    expect(mockRemove).not.toHaveBeenCalled()

    // re-open and confirm
    await user.click(screen.getByRole('button', { name: /^remove$/i }))
    await user.click(screen.getByRole('button', { name: /^remove$/i }))
    await waitFor(() => expect(mockRemove).toHaveBeenCalledWith(9))
  })
})
