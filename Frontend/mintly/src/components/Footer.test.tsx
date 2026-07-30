import { describe, it, expect } from 'vitest'
import { screen } from '@testing-library/react'
import Footer from './Footer'
import { axe, renderWithRouter } from '../test/utils'

describe('Footer', () => {
  it('renders a contentinfo landmark with a labeled Footer nav and the quick links', () => {
    renderWithRouter(<Footer />)
    expect(screen.getByRole('contentinfo')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Footer' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Search' })).toHaveAttribute('href', '/search')
    expect(screen.getByRole('link', { name: 'Portfolio' })).toHaveAttribute('href', '/portfolio')
    expect(screen.getByRole('link', { name: 'Terms' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Privacy' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Accessibility' })).toHaveAttribute('href', '/accessibility')
  })

  it('opens the external Buy Me a Coffee link safely in a new tab', () => {
    renderWithRouter(<Footer />)
    const bmc = screen.getByRole('link', { name: 'Buy me a coffee' })
    expect(bmc).toHaveAttribute('href', 'https://buymeacoffee.com/mintlytcg')
    expect(bmc).toHaveAttribute('target', '_blank')
    expect(bmc).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('has no accessibility violations', async () => {
    const { container } = renderWithRouter(<Footer />)
    expect(await axe(container)).toHaveNoViolations()
  })
})
