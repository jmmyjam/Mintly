import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import Navbar from './Navbar'
import { getToken } from '../api'
import { axe, renderWithRouter } from '../test/utils'

vi.mock('../api', () => ({ getToken: vi.fn() }))
const mockToken = vi.mocked(getToken)

describe('Navbar', () => {
  beforeEach(() => {
    mockToken.mockReturnValue(null)
  })

  it('always exposes the primary nav destinations', () => {
    renderWithRouter(<Navbar />)
    expect(screen.getByRole('link', { name: 'Search' })).toHaveAttribute('href', '/search')
    expect(screen.getByRole('link', { name: 'Scan' })).toHaveAttribute('href', '/scan')
    expect(screen.getByRole('link', { name: 'Portfolio' })).toHaveAttribute('href', '/portfolio')
  })

  it('shows Log in and Sign up when signed out', () => {
    mockToken.mockReturnValue(null)
    renderWithRouter(<Navbar />)
    expect(screen.getByRole('link', { name: 'Log in' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sign up' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Profile' })).not.toBeInTheDocument()
  })

  it('shows the labeled profile link when signed in', () => {
    mockToken.mockReturnValue('a-token')
    renderWithRouter(<Navbar />)
    // The avatar is an icon-only link, so its accessible name comes from aria-label
    expect(screen.getByRole('link', { name: 'Profile' })).toHaveAttribute('href', '/profile')
    expect(screen.queryByRole('link', { name: 'Log in' })).not.toBeInTheDocument()
  })

  it('has no accessibility violations when signed out', async () => {
    mockToken.mockReturnValue(null)
    const { container } = renderWithRouter(<Navbar />)
    expect(await axe(container)).toHaveNoViolations()
  })

  it('has no accessibility violations when signed in', async () => {
    mockToken.mockReturnValue('a-token')
    const { container } = renderWithRouter(<Navbar />)
    expect(await axe(container)).toHaveNoViolations()
  })
})
