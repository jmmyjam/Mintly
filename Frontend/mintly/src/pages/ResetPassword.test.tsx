import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import ResetPassword from './ResetPassword'
import { forgotPassword, resetPassword } from '../api'
import { axe, LocationProbe } from '../test/utils'

// Fully replaces api: the page uses forgotPassword, resetPassword and
// errorMessage. errorMessage stays real-ish so backend Error messages (429
// detail, invalid-link) surface verbatim.
vi.mock('../api', () => ({
  forgotPassword: vi.fn(),
  resetPassword: vi.fn(),
  errorMessage: (err: unknown, fallback: string) =>
    err instanceof Error && err.message ? err.message : fallback,
}))
const mockForgot = vi.mocked(forgotPassword)
const mockReset = vi.mocked(resetPassword)

// Mirrors the notice the reset flow pushes into router state on success.
function NoticeProbe() {
  const loc = useLocation()
  const notice = (loc.state as { notice?: string } | null)?.notice
  return <div data-testid="notice">{notice ?? ''}</div>
}

function renderReset(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ResetPassword />
      <LocationProbe />
      <NoticeProbe />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mockForgot.mockReset()
  mockReset.mockReset()
})

describe('ResetPassword — request-link mode (no token)', () => {
  it('renders the email request form', () => {
    renderReset('/reset-password')
    expect(screen.getByRole('heading', { name: 'Reset your password' })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Email')).toBeInTheDocument()
    // The input carries an accessible name, not just a placeholder (a11y).
    expect(screen.getByRole('textbox', { name: 'Email' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send reset link' })).toBeInTheDocument()
  })

  it('sends the reset link and swaps to the generic confirmation', async () => {
    mockForgot.mockResolvedValue('If an account exists for that email, a reset link has been sent.')
    const user = userEvent.setup()
    renderReset('/reset-password')
    await user.type(screen.getByPlaceholderText('Email'), 'ash@example.com')
    await user.click(screen.getByRole('button', { name: 'Send reset link' }))
    expect(mockForgot).toHaveBeenCalledWith('ash@example.com')
    expect(await screen.findByText(/reset link has been sent/)).toBeInTheDocument()
    expect(screen.getByText(/works for 30 minutes/)).toBeInTheDocument()
    // the form is replaced by the confirmation note
    expect(screen.queryByPlaceholderText('Email')).not.toBeInTheDocument()
  })

  it('surfaces a rate-limit (429) detail inline and keeps the form', async () => {
    mockForgot.mockRejectedValue(new Error('Too many requests. Please wait a moment and try again.'))
    const user = userEvent.setup()
    renderReset('/reset-password')
    await user.type(screen.getByPlaceholderText('Email'), 'ash@example.com')
    await user.click(screen.getByRole('button', { name: 'Send reset link' }))
    expect(
      await screen.findByText('Too many requests. Please wait a moment and try again.'),
    ).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Email')).toBeInTheDocument()
  })

  it('has no accessibility violations', async () => {
    const { container } = renderReset('/reset-password')
    expect(await axe(container)).toHaveNoViolations()
  })
})

describe('ResetPassword — new-password mode (?token=)', () => {
  it('renders the new-password form', () => {
    renderReset('/reset-password?token=reset-tok')
    expect(screen.getByRole('heading', { name: 'Choose a new password' })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('New password')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Confirm new password')).toBeInTheDocument()
    // Password inputs expose no ARIA role, so lock their accessible names via label.
    expect(screen.getByLabelText('New password')).toBeInTheDocument()
    expect(screen.getByLabelText('Confirm new password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Set new password' })).toBeInTheDocument()
  })

  it('mirrors the backend password rule before calling the API', async () => {
    const user = userEvent.setup()
    renderReset('/reset-password?token=reset-tok')
    await user.type(screen.getByPlaceholderText('New password'), 'short')
    await user.type(screen.getByPlaceholderText('Confirm new password'), 'short')
    await user.click(screen.getByRole('button', { name: 'Set new password' }))
    expect(screen.getByText('Password must be at least 8 characters')).toBeInTheDocument()
    expect(mockReset).not.toHaveBeenCalled()
  })

  it('rejects a confirm mismatch client-side', async () => {
    const user = userEvent.setup()
    renderReset('/reset-password?token=reset-tok')
    await user.type(screen.getByPlaceholderText('New password'), 'password1')
    await user.type(screen.getByPlaceholderText('Confirm new password'), 'password2')
    await user.click(screen.getByRole('button', { name: 'Set new password' }))
    expect(screen.getByText('New passwords do not match')).toBeInTheDocument()
    expect(mockReset).not.toHaveBeenCalled()
  })

  it('resets the password and routes to /login with the updated notice', async () => {
    mockReset.mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderReset('/reset-password?token=reset-tok')
    await user.type(screen.getByPlaceholderText('New password'), 'password1')
    await user.type(screen.getByPlaceholderText('Confirm new password'), 'password1')
    await user.click(screen.getByRole('button', { name: 'Set new password' }))
    expect(mockReset).toHaveBeenCalledWith('reset-tok', 'password1')
    expect(screen.getByTestId('location')).toHaveTextContent('/login')
    expect(screen.getByTestId('notice')).toHaveTextContent(
      'Your password has been updated. Log in with your new password.',
    )
  })

  it('renders an invalid-link error with a "Request a new link" affordance', async () => {
    mockReset.mockRejectedValue(new Error('This reset link is invalid or has expired.'))
    const user = userEvent.setup()
    renderReset('/reset-password?token=stale-tok')
    await user.type(screen.getByPlaceholderText('New password'), 'password1')
    await user.type(screen.getByPlaceholderText('Confirm new password'), 'password1')
    await user.click(screen.getByRole('button', { name: 'Set new password' }))
    expect(await screen.findByText(/This reset link is invalid or has expired\./)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Request a new link' })).toHaveAttribute(
      'href',
      '/reset-password',
    )
  })

  it('has no accessibility violations', async () => {
    const { container } = renderReset('/reset-password?token=reset-tok')
    expect(await axe(container)).toHaveNoViolations()
  })
})
