import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import OAuthCallback from './OAuthCallback'
import { setToken } from '../api'
import { clearPortfolios } from '../portfolios'
import { invalidateOwned } from '../owned'
import { axe, LocationProbe } from '../test/utils'

// The page reads the JWT off window.location.hash (never the router), then
// stores it and drops any cached account data before landing on the portfolio.
vi.mock('../api', () => ({ setToken: vi.fn() }))
vi.mock('../portfolios', () => ({ clearPortfolios: vi.fn() }))
vi.mock('../owned', () => ({ invalidateOwned: vi.fn() }))

// Mirrors the notice carried in router state so the missing-token bounce can be
// asserted (LocationProbe only reflects pathname + search).
function NoticeProbe() {
  const loc = useLocation()
  const notice = (loc.state as { notice?: string } | null)?.notice
  return <div data-testid="notice">{notice ?? ''}</div>
}

function renderCallback() {
  return render(
    <MemoryRouter initialEntries={['/auth/callback']}>
      <OAuthCallback />
      <LocationProbe />
      <NoticeProbe />
    </MemoryRouter>,
  )
}

describe('OAuthCallback page', () => {
  beforeEach(() => {
    // Fully clear any hash left by a previous test.
    window.history.replaceState(null, '', '/')
  })
  afterEach(() => {
    window.history.replaceState(null, '', '/')
  })

  it('stores the token from the URL fragment and replaces to the portfolio', async () => {
    window.location.hash = '#token=jwt.abc.123'
    renderCallback()
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/portfolio'))
    expect(setToken).toHaveBeenCalledWith('jwt.abc.123')
    // clearPortfolios/invalidateOwned are idempotent; the effect can re-run once
    // react-router hands it a fresh `navigate` after the redirect, so assert
    // "at least once" rather than an exact count.
    expect(clearPortfolios).toHaveBeenCalled()
    expect(invalidateOwned).toHaveBeenCalled()
  })

  it('URL-decodes the token before storing it', async () => {
    window.location.hash = '#token=a%2Bb%3Dc'
    renderCallback()
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/portfolio'))
    expect(setToken).toHaveBeenCalledWith('a+b=c')
  })

  it('bounces to /login with a notice when the fragment carries no token', async () => {
    window.location.hash = ''
    renderCallback()
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/login'))
    expect(screen.getByTestId('notice')).toHaveTextContent(
      "We couldn't complete sign-in. Please try again.",
    )
    expect(setToken).not.toHaveBeenCalled()
    expect(clearPortfolios).not.toHaveBeenCalled()
  })

  it('shows a signing-in message while it works', () => {
    window.location.hash = '#token=abc'
    renderCallback()
    expect(screen.getByText('Signing you in...')).toBeInTheDocument()
  })

  it('has no accessibility violations', async () => {
    window.location.hash = '#token=abc'
    const { container } = renderCallback()
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/portfolio'))
    expect(await axe(container)).toHaveNoViolations()
  })
})
