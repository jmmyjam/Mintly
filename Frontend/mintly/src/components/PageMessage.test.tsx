import { describe, it, expect } from 'vitest'
import { screen } from '@testing-library/react'
import PageMessage from './PageMessage'
import NotFoundMessage from './NotFoundMessage'
import { axe, renderWithRouter } from '../test/utils'

describe('PageMessage', () => {
  it('renders its message', () => {
    renderWithRouter(<PageMessage>Loading your portfolio…</PageMessage>)
    expect(screen.getByText('Loading your portfolio…')).toBeInTheDocument()
  })

  it('renders a CTA link when an action is provided', () => {
    renderWithRouter(
      <PageMessage action={{ to: '/login', label: 'Log in' }}>Please sign in</PageMessage>,
    )
    expect(screen.getByRole('link', { name: 'Log in' })).toHaveAttribute('href', '/login')
  })

  it('omits the CTA when no action is provided', () => {
    renderWithRouter(<PageMessage>Just a message</PageMessage>)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('has no accessibility violations', async () => {
    const { container } = renderWithRouter(
      <PageMessage action={{ to: '/', label: 'Home' }}>Message</PageMessage>,
    )
    expect(await axe(container)).toHaveNoViolations()
  })
})

describe('NotFoundMessage', () => {
  it('renders the not-found heading and a link home', () => {
    renderWithRouter(<NotFoundMessage />)
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to home' })).toHaveAttribute('href', '/')
  })

  it('has no accessibility violations', async () => {
    const { container } = renderWithRouter(<NotFoundMessage />)
    expect(await axe(container)).toHaveNoViolations()
  })
})
