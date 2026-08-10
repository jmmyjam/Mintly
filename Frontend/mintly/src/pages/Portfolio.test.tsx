import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Portfolio from './Portfolio'
import {
  getPortfolio, getPortfolioHistory, getSetCompletion, getToken,
  type PortfolioCard, type HistoryPoint, type SetCompletion,
} from '../api'
import { axe, renderWithRouter } from '../test/utils'

// Mock only the network fns; keep the pure helpers (getCardImageUrl,
// CONNECTION_ERROR, SessionExpiredError) real via the importActual spread so the
// page renders exactly as it does in production.
vi.mock('../api', async (importActual) => {
  const actual = await importActual<typeof import('../api')>()
  return {
    ...actual,
    getPortfolio: vi.fn(),
    getPortfolioHistory: vi.fn(),
    getSetCompletion: vi.fn(),
    getToken: vi.fn(),
  }
})

// The active-portfolio store is stubbed to a single loaded portfolio (id 1) — the
// outer component keys PortfolioView to this id. PortfolioSelector in the header
// reads the same hook.
vi.mock('../portfolios', () => ({
  usePortfolios: () => ({
    portfolios: [{ id: 1, name: 'My Portfolio', is_default: true, created_at: '', card_count: 3 }],
    active: { id: 1, name: 'My Portfolio', is_default: true, created_at: '', card_count: 3 },
    activeId: 1,
    setActive: vi.fn(),
    refresh: vi.fn(),
    loaded: true,
  }),
  clearPortfolios: vi.fn(),
}))


const mockGetPortfolio = vi.mocked(getPortfolio)
const mockGetHistory = vi.mocked(getPortfolioHistory)
const mockGetCompletion = vi.mocked(getSetCompletion)
const mockToken = vi.mocked(getToken)

function lot(over: Partial<PortfolioCard> & { id: number; card_id: string; card_name: string }): PortfolioCard {
  return {
    quantity: 1,
    purchase_price: 10,
    purchase_date: '2026-01-01T00:00:00',
    current_price: 10,
    gain_loss: 0,
    gain_loss_pct: 0,
    price_change: null,
    image_url: null,
    ...over,
  }
}

// Three cards / six lots: a gainer (Charizard, with a day-change), a loser
// (Blastoise), and another gainer (Venusaur).
const LOTS: PortfolioCard[] = [
  lot({
    id: 1, card_id: 'base1-4', card_name: 'Charizard', quantity: 2,
    purchase_price: 100, current_price: 150, gain_loss: 100, gain_loss_pct: 50,
    price_change: { amount: 5, percent: 3.4, since: '2026-08-08T00:00:00' },
  }),
  lot({
    id: 2, card_id: 'base1-2', card_name: 'Blastoise', quantity: 1,
    purchase_price: 80, current_price: 60, gain_loss: -20, gain_loss_pct: -25,
  }),
  lot({
    id: 3, card_id: 'base1-15', card_name: 'Venusaur', quantity: 3,
    purchase_price: 20, current_price: 30, gain_loss: 30, gain_loss_pct: 50,
  }),
]

const HISTORY: HistoryPoint[] = [
  { date: '2026-07-01', total_value: 400 },
  { date: '2026-08-08', total_value: 450 },
]

const COMPLETION: SetCompletion[] = [
  {
    set_id: 'base1', set_name: 'Base Set', series: 'Original', release_date: '1999-01-09',
    printed_total: 102, owned: 3, total: 102, logo: null, symbol: null,
  },
]

beforeEach(() => {
  localStorage.clear()
  mockToken.mockReturnValue('test-token')
  mockGetPortfolio.mockResolvedValue(LOTS)
  mockGetHistory.mockResolvedValue(HISTORY)
  mockGetCompletion.mockResolvedValue(COMPLETION)
})

describe('Portfolio page — signed out', () => {
  it('shows the SignedOutHero portfolio pitch and fetches no data', async () => {
    mockToken.mockReturnValue(null as unknown as string)
    renderWithRouter(<Portfolio />)

    expect(screen.getByRole('heading', { name: /Track your collection.s value over time/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Log in' })).toHaveAttribute('href', '/login')
    expect(screen.getByRole('link', { name: /Create a free account/i })).toBeInTheDocument()
    expect(mockGetPortfolio).not.toHaveBeenCalled()
  })
})

describe('Portfolio page — signed in with holdings', () => {
  it('renders the hero value, cost basis and card/lot count from the lots', async () => {
    renderWithRouter(<Portfolio />)

    // Hero value ($450.00 = 150*2 + 60 + 30) — the dollars sit in their own text node
    expect(await screen.findByText('$450')).toBeInTheDocument()
    expect(screen.getByText('Portfolio value')).toBeInTheDocument()
    // Cost basis = 100*2 + 80 + 20*3 = 340
    expect(screen.getByText('Cost basis')).toBeInTheDocument()
    expect(screen.getByText('$340.00')).toBeInTheDocument()
    // 3 grouped cards, 3 lot rows (the count row)
    expect(screen.getByText('3 cards · 3 lots')).toBeInTheDocument()
  })

  it('renders a holdings tile per card, each linking to /portfolio/:cardId with its Qty', async () => {
    renderWithRouter(<Portfolio />)

    const charizard = await screen.findByText('Charizard')
    expect(charizard.closest('a')).toHaveAttribute('href', '/portfolio/base1-4')
    expect(screen.getByText('Blastoise').closest('a')).toHaveAttribute('href', '/portfolio/base1-2')
    expect(screen.getByText('Venusaur').closest('a')).toHaveAttribute('href', '/portfolio/base1-15')

    // Charizard: qty 2 across its single lot
    expect(screen.getByText('Qty 2')).toBeInTheDocument()
    // The trailing dashed "Add a card" cell links to search
    expect(screen.getByRole('link', { name: /Add a card/i })).toHaveAttribute('href', '/search')
  })

  it('shows the value-over-time chart panel', async () => {
    renderWithRouter(<Portfolio />)
    expect(await screen.findByText('Value over time')).toBeInTheDocument()
  })

  it('filters the visible tiles by the name filter', async () => {
    const user = userEvent.setup()
    renderWithRouter(<Portfolio />)
    await screen.findByText('Charizard')

    await user.type(screen.getByPlaceholderText('Filter by name'), 'char')

    expect(screen.getByText('Charizard')).toBeInTheDocument()
    expect(screen.queryByText('Blastoise')).not.toBeInTheDocument()
    expect(screen.queryByText('Venusaur')).not.toBeInTheDocument()
    expect(screen.getByText('1 of 3 cards')).toBeInTheDocument()
  })

  it('the Losers segment narrows to cards with a loss', async () => {
    const user = userEvent.setup()
    renderWithRouter(<Portfolio />)
    await screen.findByText('Charizard')

    await user.click(screen.getByRole('button', { name: 'Losers' }))

    expect(screen.getByText('Blastoise')).toBeInTheDocument()
    expect(screen.queryByText('Charizard')).not.toBeInTheDocument()
    expect(screen.queryByText('Venusaur')).not.toBeInTheDocument()
  })

  it('offers the sort control with its options', async () => {
    renderWithRouter(<Portfolio />)
    await screen.findByText('Charizard')

    const sort = screen.getByRole('combobox')
    expect(within(sort).getByRole('option', { name: 'Highest value' })).toBeInTheDocument()
    expect(within(sort).getByRole('option', { name: 'Biggest gain' })).toBeInTheDocument()
  })

  it('renders the Set completion rollup from getSetCompletion', async () => {
    renderWithRouter(<Portfolio />)

    expect(await screen.findByRole('heading', { name: 'Set completion' })).toBeInTheDocument()
    const setLink = screen.getByRole('link', { name: /Base Set/ })
    expect(setLink).toHaveAttribute('href', '/search?set=base1')
    expect(screen.getByRole('progressbar', { name: /Base Set/ })).toBeInTheDocument()
  })

  it('has no accessibility violations on the loaded state', async () => {
    const { container } = renderWithRouter(<Portfolio />)
    await screen.findByText('Charizard')
    await screen.findByRole('heading', { name: 'Set completion' })
    expect(await axe(container)).toHaveNoViolations()
  })
})

describe('Portfolio page — empty portfolio', () => {
  beforeEach(() => {
    mockGetPortfolio.mockResolvedValue([])
    mockGetCompletion.mockResolvedValue([])
  })

  it('shows the empty state with a Search link and the CSV import affordance', async () => {
    renderWithRouter(<Portfolio />)

    expect(await screen.findByText(/No cards in this portfolio yet/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Search Cards' })).toHaveAttribute('href', '/search')
    // The kebab menu (Import/Export) stays reachable so a collection can be seeded
    expect(screen.getByRole('button', { name: 'Import or export CSV' })).toBeInTheDocument()
  })
})
