import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import HeroSearch from './HeroSearch'
import { setSettings } from '../accessibility'
import { axe, renderWithRouter } from '../test/utils'

// Reduce-motion off runs the placeholder typewriter (a setTimeout loop) for the
// life of the component; pin it on so these tests have no background timers and
// the placeholder is the static fallback.
beforeEach(() => {
  setSettings({ reduceMotion: true })
})
afterEach(() => {
  setSettings({ reduceMotion: false })
})

describe('HeroSearch', () => {
  it('gives the search field a stable accessible name', () => {
    renderWithRouter(<HeroSearch />)
    expect(screen.getByRole('textbox', { name: 'Search cards by name' })).toBeInTheDocument()
  })

  it('uses a static (aria-hidden) placeholder overlay under reduce-motion', () => {
    renderWithRouter(<HeroSearch />)
    expect(screen.getByText('Try "charizard base"')).toBeInTheDocument()
  })

  it('navigates to /search with the encoded query on submit', async () => {
    const user = userEvent.setup()
    renderWithRouter(<HeroSearch />, { withProbe: true })
    await user.type(screen.getByRole('textbox', { name: 'Search cards by name' }), 'charizard base')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/search?q=charizard%20base')
  })

  it('does not navigate on an empty/whitespace query', async () => {
    const user = userEvent.setup()
    renderWithRouter(<HeroSearch />, { withProbe: true })
    await user.type(screen.getByRole('textbox', { name: 'Search cards by name' }), '   ')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/')
    expect(screen.getByTestId('location')).not.toHaveTextContent('/search')
  })

  it('navigates when a "Try" chip is clicked', async () => {
    const user = userEvent.setup()
    renderWithRouter(<HeroSearch />, { withProbe: true })
    await user.click(screen.getByRole('button', { name: 'Charizard' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/search?q=Charizard')
  })

  it('has no accessibility violations', async () => {
    const { container } = renderWithRouter(<HeroSearch />)
    expect(await axe(container)).toHaveNoViolations()
  })
})
