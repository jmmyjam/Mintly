import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import VerifyEmail from './VerifyEmail'
import { verifyEmail } from '../api'
import { axe, renderWithRouter } from '../test/utils'

// The page fully replaces the api module: it only reaches for verifyEmail and
// errorMessage. errorMessage stays real-ish so a rejected verifyEmail surfaces
// its Error message (the failure copy) verbatim.
vi.mock('../api', () => ({
  verifyEmail: vi.fn(),
  errorMessage: (err: unknown, fallback: string) =>
    err instanceof Error && err.message ? err.message : fallback,
}))
const mockVerify = vi.mocked(verifyEmail)

describe('VerifyEmail page', () => {
  beforeEach(() => {
    mockVerify.mockReset()
  })

  it('shows the missing-token failure without calling the API when there is no token', () => {
    renderWithRouter(<VerifyEmail />, { route: '/verify-email' })
    expect(screen.getByRole('heading', { name: 'Verification failed' })).toBeInTheDocument()
    expect(screen.getByText('This verification link is missing its token.')).toBeInTheDocument()
    expect(mockVerify).not.toHaveBeenCalled()
  })

  it('shows the verifying state while the request is in flight', () => {
    mockVerify.mockReturnValue(new Promise<void>(() => {}))
    renderWithRouter(<VerifyEmail />, { route: '/verify-email?token=abc' })
    expect(screen.getByRole('heading', { name: /Verifying your email/ })).toBeInTheDocument()
    expect(mockVerify).toHaveBeenCalledWith('abc')
  })

  it('confirms the email and links to the portfolio on a valid token', async () => {
    mockVerify.mockResolvedValue(undefined)
    renderWithRouter(<VerifyEmail />, { route: '/verify-email?token=good-token' })
    expect(await screen.findByRole('heading', { name: 'Email verified' })).toBeInTheDocument()
    expect(mockVerify).toHaveBeenCalledWith('good-token')
    expect(screen.getByRole('link', { name: 'Go to your portfolio' })).toHaveAttribute('href', '/portfolio')
  })

  it('surfaces the backend error message when the token is rejected', async () => {
    mockVerify.mockRejectedValue(new Error('This verification link has expired.'))
    renderWithRouter(<VerifyEmail />, { route: '/verify-email?token=bad-token' })
    expect(await screen.findByRole('heading', { name: 'Verification failed' })).toBeInTheDocument()
    expect(screen.getByText('This verification link has expired.')).toBeInTheDocument()
  })

  it('has no accessibility violations', async () => {
    mockVerify.mockResolvedValue(undefined)
    const { container } = renderWithRouter(<VerifyEmail />, { route: '/verify-email?token=good-token' })
    await screen.findByRole('heading', { name: 'Email verified' })
    expect(await axe(container)).toHaveNoViolations()
  })
})
