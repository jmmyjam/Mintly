import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import CardDetail from './CardDetail'
import { getCard, getCardHistory, getEbayEstimate, filterCards } from '../api'
import type { Card, CardHistory, EbayEstimate } from '../api'
import { invalidateSetCompletion } from '../setCompletion'
import { axe, renderWithRouter } from '../test/utils'

// Stub only the network calls; getCardPrice, the affiliate builders, the error
// constants/classes and getToken (null while signed out) stay real.
vi.mock('../api', async (importActual) => {
  const actual = await importActual<typeof import('../api')>()
  return {
    ...actual,
    getCard: vi.fn(),
    getCardHistory: vi.fn(),
    getEbayEstimate: vi.fn(),
    filterCards: vi.fn(),
    getSetCompletion: vi.fn(),
    getPortfolios: vi.fn(),
    getPortfolio: vi.fn(),
    addCard: vi.fn(),
  }
})

const mockGetCard = vi.mocked(getCard)
const mockGetHistory = vi.mocked(getCardHistory)
const mockGetEbay = vi.mocked(getEbayEstimate)
const mockFilter = vi.mocked(filterCards)

const DEFAULT_TITLE = 'Mintly - Pokémon TCG Portfolio Tracker'

function pricedCard(over: Partial<Card> = {}): Card {
  return {
    id: 'base1-4',
    name: 'Charizard',
    number: '4',
    rarity: 'Rare Holo',
    images: { small: 's.png', large: 'l.png' },
    set: { id: 'base1', name: 'Base Set', series: 'Base', printedTotal: 102, releaseDate: '1999/01/09' },
    tcgplayer: {
      url: 'https://www.tcgplayer.com/product/42',
      updatedAt: '2026-08-08',
      prices: { holofoil: { market: 100, low: 80, mid: 95, high: 150 } },
    },
    ...over,
  }
}

const HISTORY: CardHistory = {
  points: [
    { date: '2026-08-01', price: 90 },
    { date: '2026-08-08', price: 100 },
  ],
  variants: {},
}

function renderDetail(route = '/card/base1-4') {
  return renderWithRouter(
    <Routes>
      <Route path="/card/:cardId" element={<CardDetail />} />
    </Routes>,
    { route },
  )
}

beforeEach(() => {
  localStorage.clear()
  invalidateSetCompletion()
  document.title = DEFAULT_TITLE
  mockGetCard.mockResolvedValue(pricedCard())
  mockGetHistory.mockResolvedValue(HISTORY)
  mockFilter.mockResolvedValue({ data: [], page: 1, pageSize: 50, totalCount: 0 })
  mockGetEbay.mockResolvedValue({
    count: 0, median: null, average: null, low: null, high: null,
    currency: 'USD', since: null, until: null,
    source_url: 'https://www.ebay.com/sch/i.html?_nkw=x', sample: [],
  })
})

describe('CardDetail', () => {
  it('renders the card name, set, market price and source tag', async () => {
    renderDetail()

    expect(await screen.findByRole('heading', { level: 1, name: /Charizard/ })).toBeInTheDocument()
    expect(screen.getByText(/Base Set/)).toBeInTheDocument()
    expect(screen.getByText('TCGplayer market')).toBeInTheDocument()
    // Hero price + Market tile both show the market value
    expect(screen.getAllByText('$100.00').length).toBeGreaterThan(0)
  })

  it('renders the Market/Low/Mid/High KPI tiles', async () => {
    renderDetail()
    await screen.findByRole('heading', { level: 1, name: /Charizard/ })

    for (const label of ['Market', 'Low', 'Mid', 'High']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(screen.getByText('$80.00')).toBeInTheDocument()   // Low (unique)
    expect(screen.getByText('$150.00')).toBeInTheDocument()  // High (unique)
  })

  it('builds the outbound buy links (non-affiliate in this env)', async () => {
    renderDetail()

    const tcg = await screen.findByRole('link', { name: /Buy on TCGplayer/ })
    expect(tcg).toHaveAttribute('href', 'https://www.tcgplayer.com/product/42')
    expect(tcg).toHaveAttribute('rel', 'noopener noreferrer')

    const ebay = screen.getByRole('link', { name: /Search on eBay/ })
    expect(ebay).toHaveAttribute('href', expect.stringContaining('ebay.com/sch/i.html'))
    expect(ebay.getAttribute('href')).toContain('Charizard')
    expect(ebay).toHaveAttribute('rel', 'noopener noreferrer')

    // No affiliate ids configured → no FTC commission line
    expect(screen.queryByText(/may earn a commission/)).not.toBeInTheDocument()
  })

  it('emits a Product JSON-LD block with no offers', async () => {
    const { container } = renderDetail()
    await screen.findByRole('heading', { level: 1, name: /Charizard/ })

    const script = container.querySelector('script[type="application/ld+json"]')
    expect(script).toBeTruthy()
    const data = JSON.parse(script!.textContent!)
    expect(data['@type']).toBe('Product')
    expect(data.name).toBe('Charizard')
    expect(data.offers).toBeUndefined()
  })

  it('sets the document title on load and restores it on unmount', async () => {
    const { unmount } = renderDetail()
    await waitFor(() => expect(document.title).toContain('Charizard'))
    expect(document.title).toBe('Charizard · Base Set - Mintly')

    unmount()
    expect(document.title).toBe(DEFAULT_TITLE)
  })

  it('falls back to an eBay estimate for a priceless card', async () => {
    mockGetCard.mockResolvedValue(pricedCard({ tcgplayer: undefined }))
    const estimate: EbayEstimate = {
      count: 5, median: 42, average: 40, low: 30, high: 60,
      currency: 'USD', since: '2026-08-01', until: '2026-08-08',
      source_url: 'https://www.ebay.com/sch/i.html?_nkw=charizard', sample: [],
    }
    mockGetEbay.mockResolvedValue(estimate)

    renderDetail()

    expect(await screen.findByText('eBay est.')).toBeInTheDocument()
    await waitFor(() => expect(mockGetEbay).toHaveBeenCalledWith('base1-4'))
    expect(screen.getByText(/Estimated from 5 recent eBay sold listings/)).toBeInTheDocument()
    // KPI tiles become Median/Average/Low/High
    expect(screen.getByText('Median')).toBeInTheDocument()
    expect(screen.getByText('Average')).toBeInTheDocument()
    expect(screen.getByText('$40.00')).toBeInTheDocument() // Average (unique)
  })

  it('re-polls getCard while refreshing and swaps in the fresh price', async () => {
    vi.useFakeTimers()
    try {
      const stale = pricedCard({
        refreshing: true,
        tcgplayer: { prices: { holofoil: { market: 100, low: 80, mid: 95, high: 150 } } },
      })
      const fresh = pricedCard({
        refreshing: false,
        tcgplayer: { prices: { holofoil: { market: 130, low: 80, mid: 95, high: 150 } } },
      })
      mockGetCard.mockResolvedValueOnce(stale).mockResolvedValue(fresh)

      renderDetail()

      // Flush the initial load(0)
      await vi.advanceTimersByTimeAsync(0)
      expect(mockGetCard).toHaveBeenCalledTimes(1)

      // The 3s re-poll picks up the fresh price
      await vi.advanceTimersByTimeAsync(3000)
      expect(mockGetCard).toHaveBeenCalledTimes(2)
      expect(screen.getAllByText('$130.00').length).toBeGreaterThan(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('shows a not-found message when the card fails to load', async () => {
    mockGetCard.mockRejectedValue(new Error('Card not found'))
    renderDetail()

    expect(await screen.findByText(/We couldn't find that card/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to Search' })).toBeInTheDocument()
  })

  it('has no accessibility violations on a loaded card page', async () => {
    const { container } = renderDetail()
    await screen.findByRole('heading', { level: 1, name: /Charizard/ })
    expect(await axe(container)).toHaveNoViolations()
  })
})
