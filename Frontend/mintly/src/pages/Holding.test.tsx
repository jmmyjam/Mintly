import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import Holding from './Holding'
import {
  getPortfolio, getCard, removeCard, updateCard, getCardHistory, getToken,
  type PortfolioCard, type Card, type CardHistory,
} from '../api'
import { axe, renderWithRouter } from '../test/utils'

// Mock the network fns; getCardPrice (source label), money/signedMoney,
// getCardImageUrl, CONNECTION_ERROR and SessionExpiredError stay real via the
// importActual spread. getCardHistory is stubbed so the embedded PriceHistoryChart
// renders its "not enough history" note instead of reaching the network.
vi.mock('../api', async (importActual) => {
  const actual = await importActual<typeof import('../api')>()
  return {
    ...actual,
    getPortfolio: vi.fn(),
    getCard: vi.fn(),
    removeCard: vi.fn(),
    updateCard: vi.fn(),
    getCardHistory: vi.fn(),
    getToken: vi.fn(),
  }
})

// Active-portfolio store: a single loaded portfolio (id 1). Holding scopes
// getPortfolio(activeId) to it.
vi.mock('../portfolios', () => ({
  usePortfolios: () => ({
    portfolios: [{ id: 1, name: 'My Portfolio', is_default: true, created_at: '', card_count: 2 }],
    active: { id: 1, name: 'My Portfolio', is_default: true, created_at: '', card_count: 2 },
    activeId: 1,
    setActive: vi.fn(),
    refresh: vi.fn(),
    loaded: true,
  }),
  clearPortfolios: vi.fn(),
}))

const mockGetPortfolio = vi.mocked(getPortfolio)
const mockGetCard = vi.mocked(getCard)
const mockRemoveCard = vi.mocked(removeCard)
const mockUpdateCard = vi.mocked(updateCard)
const mockGetHistory = vi.mocked(getCardHistory)
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
    grading: null,
    grade: null,
    ...over,
  }
}

const CHANGE = { amount: 5, percent: 3.4, since: '2026-08-08T00:00:00' }

// base1-4 has TWO lots (multi-lot position); base1-2 is a second card so the
// prev/next pager has somewhere to walk.
const LOTS: PortfolioCard[] = [
  lot({
    id: 1, card_id: 'base1-4', card_name: 'Charizard', quantity: 2,
    purchase_price: 100, purchase_date: '2026-01-01T00:00:00',
    current_price: 150, gain_loss: 100, gain_loss_pct: 50, price_change: CHANGE,
  }),
  lot({
    id: 2, card_id: 'base1-4', card_name: 'Charizard', quantity: 1,
    purchase_price: 120, purchase_date: '2026-03-01T00:00:00',
    current_price: 150, gain_loss: 30, gain_loss_pct: 25, price_change: CHANGE,
  }),
  lot({
    id: 3, card_id: 'base1-2', card_name: 'Blastoise', quantity: 1,
    purchase_price: 80, purchase_date: '2026-02-01T00:00:00',
    current_price: 60, gain_loss: -20, gain_loss_pct: -25,
  }),
]

const CARD: Card = {
  id: 'base1-4',
  name: 'Charizard',
  number: '4',
  images: { small: '', large: '' },
  set: { name: 'Base Set', id: 'base1', printedTotal: 102 },
  tcgplayer: { prices: { holofoil: { market: 150 } } },
}

const EMPTY_HISTORY: CardHistory = { points: [], variants: {} }

function renderHolding(route = '/portfolio/base1-4') {
  return renderWithRouter(
    <Routes>
      <Route path="/portfolio/:cardId" element={<Holding />} />
      <Route path="/portfolio" element={<div>Portfolio index</div>} />
    </Routes>,
    { route, withProbe: true },
  )
}

beforeEach(() => {
  localStorage.clear()
  mockToken.mockReturnValue('test-token')
  mockGetPortfolio.mockResolvedValue(LOTS)
  mockGetCard.mockResolvedValue(CARD)
  mockGetHistory.mockResolvedValue(EMPTY_HISTORY)
  mockRemoveCard.mockResolvedValue('Removed' as unknown as void)
  mockUpdateCard.mockResolvedValue('Updated' as unknown as void)
})

describe('Holding page — signed out', () => {
  it('shows the SignedOutHero portfolio pitch and fetches no data', async () => {
    mockToken.mockReturnValue(null as unknown as string)
    renderHolding()

    expect(screen.getByRole('heading', { name: /Track your collection.s value over time/i })).toBeInTheDocument()
    expect(mockGetPortfolio).not.toHaveBeenCalled()
  })
})

describe('Holding page — loaded position', () => {
  it('renders the position panel figures from the shared portfolio math', async () => {
    renderHolding()

    // Title + owned pill (qty across both lots = 3)
    expect(await screen.findByRole('heading', { level: 1, name: 'Charizard' })).toBeInTheDocument()
    expect(screen.getByText('×3 owned')).toBeInTheDocument()
    // Sub-line: set/number + purchase count since the first lot's date
    expect(screen.getByText(/Base Set · #4\/102 · 2 purchases since Jan 1, 2026/)).toBeInTheDocument()

    // Your value = 150*3 = 450; cost basis = 100*2 + 120 = 320; P&L = +130; market = 150
    expect(screen.getByText('Your value')).toBeInTheDocument()
    expect(screen.getByText('$450.00')).toBeInTheDocument()
    expect(screen.getByText('Cost basis')).toBeInTheDocument()
    expect(screen.getByText(/avg \$106\.67 each/)).toBeInTheDocument()
    // +$130.00 appears in the Total P&L cell and again in the totals row
    expect(screen.getAllByText('+$130.00').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Market now')).toBeInTheDocument()
    expect(screen.getByText('$150.00')).toBeInTheDocument()
    // Source label comes from getCardPrice(card) (real) — TCGplayer market present
    expect(screen.getByText('TCGplayer market')).toBeInTheDocument()
  })

  it('lists one purchases row per lot plus a totals row', async () => {
    renderHolding()
    await screen.findByRole('heading', { level: 1, name: 'Charizard' })

    // Lot 1 (qty 2 @ $100): paid $100.00, cost $200.00 — both unique to this row
    expect(screen.getByText('$100.00')).toBeInTheDocument()
    expect(screen.getByText('$200.00')).toBeInTheDocument()
    // Lot 2 (qty 1 @ $120): $120.00 shows as both paid-each and cost
    expect(screen.getAllByText('$120.00').length).toBeGreaterThanOrEqual(2)
    // Totals row (cost $320.00 also appears in the Cost basis stat)
    expect(screen.getByText('Total')).toBeInTheDocument()
    expect(screen.getAllByText('$320.00').length).toBeGreaterThanOrEqual(1)
  })

  it('has a prev/next pager across the portfolio order', async () => {
    renderHolding()
    await screen.findByRole('heading', { level: 1, name: 'Charizard' })

    // base1-4 is newest, so it's holding 1 of 2 — prev disabled, next enabled
    expect(screen.getByText(/holding 1 of 2/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous holding' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Next holding' })).toBeEnabled()
  })

  it('reveals the add-purchase form pre-filled to market', async () => {
    const user = userEvent.setup()
    renderHolding()
    await screen.findByRole('heading', { level: 1, name: 'Charizard' })

    await user.click(screen.getByRole('button', { name: 'Add purchase' }))

    expect(screen.getByText('Add a purchase')).toBeInTheDocument()
    // openAdd pre-fills the price with market.toFixed(2)
    expect(screen.getByLabelText('Price paid ($)')).toHaveValue(150)
    expect(screen.getByLabelText('Quantity')).toHaveValue(1)
  })

  it('Edit swaps a lot row into the inline edit form', async () => {
    const user = userEvent.setup()
    renderHolding()
    await screen.findByRole('heading', { level: 1, name: 'Charizard' })

    // Newest lot first (id 2, paid $120)
    await user.click(screen.getAllByRole('button', { name: 'Edit' })[0])

    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
    expect(screen.getByLabelText('Price paid ($)')).toHaveValue(120)
  })

  it('Remove is a two-step confirm that calls removeCard', async () => {
    const user = userEvent.setup()
    renderHolding()
    await screen.findByRole('heading', { level: 1, name: 'Charizard' })

    // First Remove button belongs to the newest lot (id 2)
    await user.click(screen.getAllByRole('button', { name: 'Remove' })[0])
    // Step two: a Confirm button appears
    const confirm = await screen.findByRole('button', { name: 'Confirm' })
    await user.click(confirm)

    expect(mockRemoveCard).toHaveBeenCalledWith(2)
  })

  it('has no accessibility violations on the loaded state', async () => {
    const { container } = renderHolding()
    await screen.findByRole('heading', { level: 1, name: 'Charizard' })
    await screen.findByText(/Not enough history yet/i)
    expect(await axe(container)).toHaveNoViolations()
  })
})

describe('Holding page — card not owned', () => {
  it('shows the "you don\'t own this card yet" prompt', async () => {
    // getPortfolio has no lots for base1-99, so the not-owned branch renders
    renderHolding('/portfolio/base1-99')

    expect(await screen.findByText(/You don't own this card yet/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /View card & market data/i })).toHaveAttribute('href', '/card/base1-99')
  })
})
