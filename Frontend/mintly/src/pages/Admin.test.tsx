import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Admin from './Admin'
import { getAdminStats, getToken, NotAdminError, SessionExpiredError, type AdminStats } from '../api'
import { axe, renderWithRouter } from '../test/utils'

// Keep NotAdminError / SessionExpiredError real (Admin keys its denied states on
// `instanceof`); stub only the stats fetch + token accessor.
vi.mock('../api', async (importActual) => {
  const actual = await importActual<typeof import('../api')>()
  return {
    ...actual,
    getAdminStats: vi.fn(),
    getToken: vi.fn(),
  }
})

const mockGetAdminStats = vi.mocked(getAdminStats)
const mockGetToken = vi.mocked(getToken)

function makeStats(overrides: Partial<AdminStats> = {}): AdminStats {
  return {
    generated_at: '2026-08-09T12:00:00',
    users: { total: 128, new_7d: 12, new_30d: 40, with_portfolio: 64 },
    signups_by_day: [
      { date: '2026-08-01', count: 3 },
      { date: '2026-08-02', count: 5 },
      { date: '2026-08-03', count: 0 },
    ],
    recent_users: [
      { id: 1, username: 'ashketchum', email: 'ash@example.com', created_at: '2026-08-08T09:30:00', lots: 5 },
      { id: 2, username: 'mistywater', email: 'misty@example.com', created_at: '2026-08-07T14:15:00', lots: 0 },
    ],
    portfolio: { portfolios: 90, lots: 512, distinct_cards: 300, total_quantity: 780 },
    catalog: { cards: 21432, stale_prices: 7, last_full_sync: '2026-08-09T06:00:00' },
    snapshots: { rows: 100000, today: 21000, latest: '2026-08-09T06:00:00' },
    db_size_bytes: 1234567890,
    ...overrides,
  }
}

beforeEach(() => {
  mockGetToken.mockReturnValue('test-token')
  mockGetAdminStats.mockResolvedValue(makeStats())
})

describe('Admin', () => {
  it('renders the stat tiles with formatted numbers', async () => {
    renderWithRouter(<Admin />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Admin' })).toBeInTheDocument()
    // Users
    expect(screen.getByText('128')).toBeInTheDocument()
    expect(screen.getByText('64')).toBeInTheDocument()
    expect(screen.getByText('50% of accounts')).toBeInTheDocument()
    // Portfolios + data health (thousands separated / byte-formatted)
    expect(screen.getByText('512')).toBeInTheDocument()
    expect(screen.getByText('21,432')).toBeInTheDocument()
    expect(screen.getByText('1.23 GB')).toBeInTheDocument()
  })

  it('lists recent signups in a table with username and email', async () => {
    renderWithRouter(<Admin />)
    await screen.findByRole('heading', { level: 1, name: 'Admin' })
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByText('ashketchum')).toBeInTheDocument()
    expect(screen.getByText('ash@example.com')).toBeInTheDocument()
    expect(screen.getByText('mistywater')).toBeInTheDocument()
  })

  it('re-fetches stats when Refresh is clicked', async () => {
    const user = userEvent.setup()
    renderWithRouter(<Admin />)
    await screen.findByRole('heading', { level: 1, name: 'Admin' })
    expect(mockGetAdminStats).toHaveBeenCalledOnce()

    await user.click(screen.getByRole('button', { name: 'Refresh' }))
    await waitFor(() => expect(mockGetAdminStats).toHaveBeenCalledTimes(2))
  })

  it('renders the shared "Page not found" view when the stats call 404s (NotAdminError)', async () => {
    mockGetAdminStats.mockRejectedValue(new NotAdminError())
    renderWithRouter(<Admin />)
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(screen.getByText("There's nothing at this address.")).toBeInTheDocument()
  })

  it('renders "Page not found" (not a login redirect) on a session-expired error', async () => {
    mockGetAdminStats.mockRejectedValue(new SessionExpiredError())
    renderWithRouter(<Admin />, { withProbe: true })
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    // Deliberately does NOT redirect to /login (that would reveal the page exists)
    expect(screen.getByTestId('location')).not.toHaveTextContent('/login')
  })

  it('renders "Page not found" and never calls the stats API when there is no token', () => {
    mockGetToken.mockReturnValue(null)
    renderWithRouter(<Admin />)
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(mockGetAdminStats).not.toHaveBeenCalled()
  })

  it('has no accessibility violations on the loaded dashboard', async () => {
    const { container } = renderWithRouter(<Admin />)
    await screen.findByRole('heading', { level: 1, name: 'Admin' })
    expect(await axe(container)).toHaveNoViolations()
  })
})
