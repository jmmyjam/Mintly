import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Search from './Search'
import { searchCards, filterCards, getSets } from '../api'
import type { Card, CardPage, CardSet } from '../api'
import { invalidateOwned } from '../owned'
import { axe, renderWithRouter } from '../test/utils'

// Replace only the network functions; getToken/getCardPrice/getCardImageUrl and
// the error classes stay real (they're pure or read the in-memory localStorage
// the test setup installs — signed out by default, so getToken() is null).
vi.mock('../api', async (importActual) => {
  const actual = await importActual<typeof import('../api')>()
  return {
    ...actual,
    searchCards: vi.fn(),
    filterCards: vi.fn(),
    getSets: vi.fn(),
    getPortfolio: vi.fn(),
    getPortfolios: vi.fn(),
    addCard: vi.fn(),
    createPortfolio: vi.fn(),
  }
})

const mockSearch = vi.mocked(searchCards)
const mockFilter = vi.mocked(filterCards)
const mockGetSets = vi.mocked(getSets)

// Sorted newest-first by the component, so sv1 ("Scarlet & Violet") is the
// default-view "newest set".
const SETS: CardSet[] = [
  { id: 'sv1', name: 'Scarlet & Violet', series: 'Scarlet & Violet', releaseDate: '2023/03/31' },
  { id: 'base1', name: 'Base', series: 'Base', releaseDate: '1999/01/09' },
]

function card(over: Partial<Card> = {}): Card {
  return {
    id: 'base1-4',
    name: 'Charizard',
    number: '4',
    images: { small: 'https://img.test/small.png', large: 'https://img.test/large.png' },
    set: { id: 'base1', name: 'Base', series: 'Base' },
    tcgplayer: { prices: { holofoil: { market: 100, low: 80, mid: 95, high: 150 } } },
    ...over,
  }
}

function page(cards: Card[], over: Partial<CardPage> = {}): CardPage {
  return { data: cards, page: 1, pageSize: 50, totalCount: cards.length, ...over }
}

beforeEach(() => {
  localStorage.clear()
  invalidateOwned()
  mockGetSets.mockResolvedValue(SETS)
  mockSearch.mockResolvedValue(page([card()]))
  mockFilter.mockResolvedValue(page([card()]))
})

describe('Search', () => {
  it('seeds the query from ?q= and renders result tiles', async () => {
    mockSearch.mockResolvedValue(page([card()]))
    renderWithRouter(<Search />, { route: '/search?q=charizard' })

    await waitFor(() => expect(mockSearch).toHaveBeenCalledWith('charizard', 1), { timeout: 2000 })
    expect(await screen.findByText('Charizard')).toBeInTheDocument()
    expect(screen.getByText('$100.00')).toBeInTheDocument()
    // Results header, not the default "Newest set" block
    expect(screen.getByRole('heading', { name: /Results for/ })).toBeInTheDocument()
  })

  it('shows the newest set as the default view and filters by it', async () => {
    mockFilter.mockResolvedValue(page([card()], { totalCount: 102 }))
    renderWithRouter(<Search />, { route: '/search' })

    expect(await screen.findByText('Newest set')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Scarlet & Violet' })).toBeInTheDocument()
    await waitFor(() => expect(mockFilter).toHaveBeenCalledWith({ set_id: 'sv1' }, 1))
  })

  it('mirrors a typed query back into the URL', async () => {
    const user = userEvent.setup()
    renderWithRouter(<Search />, { route: '/search', withProbe: true })
    await screen.findByText('Newest set')

    await user.type(screen.getByRole('textbox', { name: 'Search cards by name' }), 'pikachu')
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/search?q=pikachu'),
    )
  })

  it('adds a dismissible chip and filters when a set facet is picked', async () => {
    const user = userEvent.setup()
    mockFilter.mockResolvedValue(page([card()]))
    renderWithRouter(<Search />, { route: '/search' })
    await screen.findByText('Newest set')

    await user.selectOptions(screen.getByRole('combobox', { name: 'All sets' }), 'base1')

    // The picked set becomes a dismissible chip button
    expect(await screen.findByRole('button', { name: /Base/ })).toBeInTheDocument()
    await waitFor(() =>
      expect(mockFilter).toHaveBeenCalledWith(
        expect.objectContaining({ set_id: ['base1'] }),
        1,
      ),
    )
  })

  it('pages forward with the Next control', async () => {
    const user = userEvent.setup()
    mockSearch.mockResolvedValue(page([card()], { totalCount: 120, pageSize: 50 }))
    renderWithRouter(<Search />, { route: '/search?q=charizard' })
    await screen.findByText('Charizard')

    expect(screen.getAllByText(/Page 1 of 3/).length).toBeGreaterThan(0)
    await user.click(screen.getAllByRole('button', { name: /Next/ })[0])
    await waitFor(() => expect(mockSearch).toHaveBeenCalledWith('charizard', 2))
  })

  it('shows the "No cards match" block for an empty result', async () => {
    mockSearch.mockResolvedValue(page([], { totalCount: 0 }))
    renderWithRouter(<Search />, { route: '/search?q=zzznothing' })

    await waitFor(() => expect(mockSearch).toHaveBeenCalledWith('zzznothing', 1), { timeout: 2000 })
    expect(await screen.findByText(/No cards match/)).toBeInTheDocument()
  })

  it('shows a "Searching…" state while a query is in flight', async () => {
    let resolve!: (v: CardPage) => void
    mockSearch.mockReturnValue(new Promise<CardPage>(r => { resolve = r }))
    renderWithRouter(<Search />, { route: '/search?q=charizard' })

    expect(await screen.findByRole('button', { name: 'Searching…' })).toBeInTheDocument()
    resolve(page([card()]))
    expect(await screen.findByText('Charizard')).toBeInTheDocument()
  })

  it('reveals the quick-add form and sends a signed-out add to /login', async () => {
    const user = userEvent.setup()
    mockSearch.mockResolvedValue(page([card()]))
    renderWithRouter(<Search />, { route: '/search?q=charizard', withProbe: true })
    await screen.findByText('Charizard')

    // The "+ Portfolio" button reveals the inline PriceQtyForm (does not add yet)
    await user.click(screen.getByRole('button', { name: 'Portfolio' }))
    expect(screen.getByLabelText('Price paid ($)')).toBeInTheDocument()
    expect(screen.getByLabelText('Quantity')).toBeInTheDocument()

    // Submitting the add while signed out routes to /login
    await user.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/login'))
  })

  it('has no accessibility violations on a loaded results page', async () => {
    mockSearch.mockResolvedValue(
      page([
        card(),
        card({
          id: 'base1-2',
          name: 'Blastoise',
          number: '2',
          tcgplayer: { prices: { holofoil: { market: 50, low: 40, mid: 45, high: 70 } } },
        }),
      ]),
    )
    const { container } = renderWithRouter(<Search />, { route: '/search?q=charizard' })
    await screen.findByText('Charizard')
    expect(await axe(container)).toHaveNoViolations()
  })
})
