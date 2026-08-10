import { describe, it, expect } from 'vitest'
import { screen } from '@testing-library/react'
import NotFound from './NotFound'
import { axe, renderWithRouter } from '../test/utils'

describe('NotFound page', () => {
  it('renders the shared page-not-found view with a link home', () => {
    renderWithRouter(<NotFound />)
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(screen.getByText("There's nothing at this address.")).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to home' })).toHaveAttribute('href', '/')
  })

  it('has no accessibility violations', async () => {
    const { container } = renderWithRouter(<NotFound />)
    expect(await axe(container)).toHaveNoViolations()
  })
})
