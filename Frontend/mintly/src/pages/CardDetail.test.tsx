import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes, useNavigate } from 'react-router-dom'
import CardDetail from './CardDetail'
import {
  getCard, getCardHistory, getEbayEstimate, filterCards, addCard,
  getPortfolios, getSetCompletion,
} from '../api'
import { clearPortfolios } from '../portfolios'
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

// The add form only reaches the network while signed in, and a signed-in
// CardDetail also hydrates the portfolio store and the set-completion cache.
function signIn() {
  localStorage.setItem('token', 'test-token')
  vi.mocked(getPortfolios).mockResolvedValue([])
  vi.mocked(getSetCompletion).mockResolvedValue([])
}

beforeEach(() => {
  localStorage.clear()
  clearPortfolios()
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

  it('re-seeds the add-form price when navigating straight to another card', async () => {
    // Regression: the /card/:cardId route element isn't remounted per card, so
    // the add form's state used to persist — navigating card A -> card B via an
    // in-page link (e.g. "Other versions") left B's form pre-filled with A's
    // auto-filled market price, and a blind Add recorded B at A's price.
    const user = userEvent.setup()
    const blastoise = pricedCard({
      id: 'base1-2', name: 'Blastoise', number: '2',
      tcgplayer: {
        url: 'https://www.tcgplayer.com/product/9', updatedAt: '2026-08-08',
        prices: { holofoil: { market: 200, low: 150, mid: 180, high: 250 } },
      },
    })
    mockGetCard.mockImplementation(async (id: string) =>
      id === 'base1-2' ? blastoise : pricedCard())

    function NavToBlastoise() {
      const navigate = useNavigate()
      return <button onClick={() => navigate('/card/base1-2')}>go-other</button>
    }
    renderWithRouter(
      <>
        <Routes>
          <Route path="/card/:cardId" element={<CardDetail />} />
        </Routes>
        <NavToBlastoise />
      </>,
      { route: '/card/base1-4' },
    )

    // Card A: form seeded to its $100 market price.
    await screen.findByRole('heading', { level: 1, name: /Charizard/ })
    expect(screen.getByLabelText('Price paid ($)')).toHaveValue(100)

    // Navigate straight to card B without leaving the route.
    await user.click(screen.getByRole('button', { name: 'go-other' }))
    await screen.findByRole('heading', { level: 1, name: /Blastoise/ })

    // The form reflects B's $200 market, not A's leftover $100.
    expect(screen.getByLabelText('Price paid ($)')).toHaveValue(200)
  })

  it('asks for a price when the lot is graded, instead of failing the add', async () => {
    // Picking a grader clears the auto-filled raw market price (a slab isn't
    // worth the ungraded figure). Submitting with it empty used to spend a round
    // trip and come back "failed to add"; now the field says it's required, says
    // why, and the submit is refused client-side with the backend's own wording.
    const user = userEvent.setup()
    signIn()
    renderDetail()
    await screen.findByRole('heading', { level: 1, name: /Charizard/ })

    await user.selectOptions(screen.getByLabelText('Grading'), 'PSA')
    expect(screen.getByLabelText(/Price paid \(\$\)/)).toHaveValue(null)
    expect(screen.getByText(/cannot fill this in from the market price/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '+ Add to Portfolio' }))
    expect(await screen.findByText('Enter the price you paid for this graded card.')).toBeInTheDocument()
    expect(vi.mocked(addCard)).not.toHaveBeenCalled()
  })

  it('adds a graded lot once a price is entered', async () => {
    const user = userEvent.setup()
    signIn()
    vi.mocked(addCard).mockResolvedValue('Added Charizard to your portfolio')
    renderDetail()
    await screen.findByRole('heading', { level: 1, name: /Charizard/ })

    await user.selectOptions(screen.getByLabelText('Grading'), 'PSA')
    await user.type(screen.getByLabelText(/Price paid \(\$\)/), '900')
    await user.click(screen.getByRole('button', { name: '+ Add to Portfolio' }))

    // null portfolio id = the account's default (no portfolios stubbed here)
    await waitFor(() => expect(vi.mocked(addCard)).toHaveBeenCalledWith(
      'base1-4', 900, 1, null, { grading: 'PSA', grade: '10' }))
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
