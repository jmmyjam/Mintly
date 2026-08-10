import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Home from './Home'
import { getToken } from '../api'
import { setSettings } from '../accessibility'
import { axe, renderWithRouter } from '../test/utils'

// Home only reads getToken; keep the rest of the module real.
vi.mock('../api', async (importActual) => {
  const actual = await importActual<typeof import('../api')>()
  return { ...actual, getToken: vi.fn() }
})

const mockGetToken = vi.mocked(getToken)

// Pin reduce-motion on so HeroSearch renders its static placeholder instead of
// running the typewriter setTimeout loop for the life of the component.
beforeEach(() => {
  setSettings({ reduceMotion: true })
  mockGetToken.mockReturnValue(null)
})
afterEach(() => {
  setSettings({ reduceMotion: false })
})

describe('Home', () => {
  it('renders the hero headline and the proof-strip facts', () => {
    renderWithRouter(<Home />)
    expect(screen.getByRole('heading', { level: 1, name: /your cards/i })).toBeInTheDocument()
    expect(screen.getByText('21,400+')).toBeInTheDocument()
    expect(screen.getByText('Daily')).toBeInTheDocument()
    expect(screen.getByText('Unlimited')).toBeInTheDocument()
    expect(screen.getByText('$0')).toBeInTheDocument()
  })

  it('shows the "Create a free account" CTA when signed out', () => {
    mockGetToken.mockReturnValue(null)
    renderWithRouter(<Home />)
    expect(screen.getByRole('link', { name: 'Create a free account' })).toHaveAttribute('href', '/login')
    expect(screen.queryByRole('link', { name: 'Open my portfolio' })).not.toBeInTheDocument()
  })

  it('shows the "Open my portfolio" CTA when signed in', () => {
    mockGetToken.mockReturnValue('test-token')
    renderWithRouter(<Home />)
    expect(screen.getByRole('link', { name: 'Open my portfolio' })).toHaveAttribute('href', '/portfolio')
    expect(screen.queryByRole('link', { name: 'Create a free account' })).not.toBeInTheDocument()
  })

  it('links the scanner section button to /scan', () => {
    renderWithRouter(<Home />)
    expect(screen.getByRole('link', { name: 'Scan a card' })).toHaveAttribute('href', '/scan')
  })

  it('navigates to /search with the query when the hero search is submitted', async () => {
    const user = userEvent.setup()
    renderWithRouter(<Home />, { withProbe: true })
    await user.type(screen.getByRole('textbox', { name: 'Search cards by name' }), 'charizard base')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/search?q=charizard%20base')
  })

  it('has no accessibility violations', async () => {
    const { container } = renderWithRouter(<Home />)
    expect(await axe(container)).toHaveNoViolations()
  })
})
