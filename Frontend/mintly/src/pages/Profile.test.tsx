import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Profile from './Profile'
import {
  getMe, updateProfile, changePassword, resendVerification, signOutOtherDevices,
  deleteAccount, getToken, clearToken, SessionExpiredError, type UserProfile,
} from '../api'
import { setSettings } from '../accessibility'
import { axe, renderWithRouter } from '../test/utils'

// Keep the pure helpers / error classes real (so `instanceof SessionExpiredError`
// works); stub only the network calls + token accessors.
vi.mock('../api', async (importActual) => {
  const actual = await importActual<typeof import('../api')>()
  return {
    ...actual,
    getMe: vi.fn(),
    updateProfile: vi.fn(),
    changePassword: vi.fn(),
    resendVerification: vi.fn(),
    signOutOtherDevices: vi.fn(),
    deleteAccount: vi.fn(),
    getToken: vi.fn(),
    clearToken: vi.fn(),
  }
})

const mockGetMe = vi.mocked(getMe)
const mockUpdateProfile = vi.mocked(updateProfile)
const mockChangePassword = vi.mocked(changePassword)
const mockResendVerification = vi.mocked(resendVerification)
const mockSignOutOthers = vi.mocked(signOutOtherDevices)
const mockGetToken = vi.mocked(getToken)
const mockClearToken = vi.mocked(clearToken)

function makeProfile(overrides: Partial<UserProfile> = {}): UserProfile {
  return {
    email: 'ash@example.com',
    username: 'ashketchum',
    created_at: '2025-01-15T10:00:00',
    accepted_terms_at: '2025-01-15T10:00:00',
    email_verified: true,
    is_admin: false,
    has_password: true,
    oauth_providers: [],
    ...overrides,
  }
}

beforeEach(() => {
  // jsdom has no IntersectionObserver, and Profile's section rail builds one on load.
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() { return [] }
      root = null
      rootMargin = ''
      thresholds = []
    } as unknown as typeof IntersectionObserver,
  )
  localStorage.clear()
  setSettings({ reduceMotion: false, highContrast: false, underlineLinks: false, textSize: 'default' })
  mockGetToken.mockReturnValue('test-token')
  mockGetMe.mockResolvedValue(makeProfile())
  vi.mocked(deleteAccount).mockResolvedValue(undefined)
})

describe('Profile', () => {
  it('renders the identity header with username and member-since once loaded', async () => {
    renderWithRouter(<Profile />)
    expect(await screen.findByRole('heading', { level: 1, name: 'ashketchum' })).toBeInTheDocument()
    expect(screen.getByText(/Member since/i)).toBeInTheDocument()
  })

  it('hides the Admin pill for a non-admin account', async () => {
    mockGetMe.mockResolvedValue(makeProfile({ is_admin: false }))
    renderWithRouter(<Profile />)
    await screen.findByRole('heading', { level: 1, name: 'ashketchum' })
    expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument()
  })

  it('shows the Admin pill (linking to /admin) for an admin account', async () => {
    mockGetMe.mockResolvedValue(makeProfile({ is_admin: true }))
    renderWithRouter(<Profile />)
    expect(await screen.findByRole('link', { name: 'Admin' })).toHaveAttribute('href', '/admin')
  })

  it('keeps Save disabled with "No changes yet" until a field changes, then saves only changed fields', async () => {
    const user = userEvent.setup()
    mockUpdateProfile.mockResolvedValue(makeProfile({ username: 'ashketchumx' }))
    renderWithRouter(<Profile />)
    await screen.findByRole('heading', { level: 1, name: 'ashketchum' })

    const save = screen.getByRole('button', { name: 'Save changes' })
    expect(save).toBeDisabled()
    expect(screen.getByText('No changes yet')).toBeInTheDocument()

    await user.type(screen.getByRole('textbox', { name: 'Username' }), 'x')
    expect(save).toBeEnabled()

    await user.click(save)
    expect(mockUpdateProfile).toHaveBeenCalledWith({ username: 'ashketchumx' })
    expect(await screen.findByText('Profile updated.')).toBeInTheDocument()
  })

  it('shows the unverified state and resends the verification email on click', async () => {
    const user = userEvent.setup()
    mockGetMe.mockResolvedValue(makeProfile({ email_verified: false }))
    mockResendVerification.mockResolvedValue('Verification email sent. Check your inbox.')
    renderWithRouter(<Profile />)

    expect(await screen.findByText('Email not verified')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Resend verification email' }))
    expect(mockResendVerification).toHaveBeenCalledOnce()
    expect(await screen.findByText('Verification email sent. Check your inbox.')).toBeInTheDocument()
  })

  it('shows the verified tag (and no resend button) for a verified email', async () => {
    mockGetMe.mockResolvedValue(makeProfile({ email_verified: true }))
    renderWithRouter(<Profile />)
    expect(await screen.findByText('Email verified')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Resend verification email' })).not.toBeInTheDocument()
  })

  it('renders the change-password form with a live strength meter for a password account', async () => {
    const user = userEvent.setup()
    renderWithRouter(<Profile />)
    await screen.findByRole('heading', { level: 1, name: 'ashketchum' })

    // Exact accessible names: the inline Show/Hide toggle sits inside the field
    // <label>, so these must not absorb its text (e.g. "New password Show").
    // A string matcher is exact, so it would fail if the toggle text bled back in.
    expect(screen.getByLabelText('Current password')).toBeInTheDocument()
    expect(screen.getByLabelText('New password')).toBeInTheDocument()
    expect(screen.getByLabelText('Confirm new password')).toBeInTheDocument()

    const newPw = screen.getByLabelText('New password')
    await user.type(newPw, 'abc')
    expect(screen.getByText('8 characters minimum')).toBeInTheDocument()
    await user.clear(newPw)
    await user.type(newPw, 'abcdefgh') // 8 letters, no digit
    expect(screen.getByText('Add a number')).toBeInTheDocument()
    await user.clear(newPw)
    await user.type(newPw, 'password1')
    expect(screen.getByText('Strong password')).toBeInTheDocument()
  })

  it('submits current + new password to changePassword', async () => {
    const user = userEvent.setup()
    mockChangePassword.mockResolvedValue(undefined)
    renderWithRouter(<Profile />)
    await screen.findByRole('heading', { level: 1, name: 'ashketchum' })

    await user.type(screen.getByLabelText(/^Current password/), 'oldpass1')
    await user.type(screen.getByLabelText(/^New password/), 'newpass1')
    await user.type(screen.getByLabelText(/^Confirm new password/), 'newpass1')
    await user.click(screen.getByRole('button', { name: 'Update password' }))

    expect(mockChangePassword).toHaveBeenCalledWith('oldpass1', 'newpass1')
    expect(await screen.findByText('Password updated.')).toBeInTheDocument()
  })

  it('replaces the password form with a reset note for a social-only account', async () => {
    mockGetMe.mockResolvedValue(makeProfile({ has_password: false, oauth_providers: ['google'] }))
    renderWithRouter(<Profile />)
    await screen.findByRole('heading', { level: 1, name: 'ashketchum' })

    expect(screen.queryByRole('button', { name: 'Update password' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/^Current password/)).not.toBeInTheDocument()
    expect(screen.getByText(/You sign in with Google/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Forgot password' })).toHaveAttribute('href', '/reset-password')
    // The connected-accounts chip is listed for the linked provider
    expect(screen.getByText('Connected accounts')).toBeInTheDocument()
    // Sign out of other devices stays available even without a password
    expect(screen.getByRole('button', { name: 'Sign out others' })).toBeInTheDocument()
  })

  it('signs out of other devices on click', async () => {
    const user = userEvent.setup()
    mockSignOutOthers.mockResolvedValue('Signed out of your other devices.')
    renderWithRouter(<Profile />)
    await screen.findByRole('heading', { level: 1, name: 'ashketchum' })

    await user.click(screen.getByRole('button', { name: 'Sign out others' }))
    expect(mockSignOutOthers).toHaveBeenCalledOnce()
    expect(await screen.findByText('Signed out of your other devices.')).toBeInTheDocument()
  })

  it('renders the Delete account danger panel', async () => {
    renderWithRouter(<Profile />)
    await screen.findByRole('heading', { level: 1, name: 'ashketchum' })
    expect(screen.getByRole('heading', { name: 'Delete account' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete account' })).toBeInTheDocument()
  })

  it('logs out: clears the token and navigates to /login', async () => {
    const user = userEvent.setup()
    renderWithRouter(<Profile />, { withProbe: true })
    await screen.findByRole('heading', { level: 1, name: 'ashketchum' })

    await user.click(screen.getByRole('button', { name: 'Log out' }))
    expect(mockClearToken).toHaveBeenCalled()
    expect(screen.getByTestId('location')).toHaveTextContent('/login')
  })

  it('redirects to /login when getMe rejects with a session-expired error', async () => {
    mockGetMe.mockRejectedValue(new SessionExpiredError())
    renderWithRouter(<Profile />, { withProbe: true })
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/login'))
  })

  it('shows the logged-out prompt when there is no token', () => {
    mockGetToken.mockReturnValue(null)
    renderWithRouter(<Profile />)
    expect(screen.getByRole('heading', { name: 'Log in to view your profile' })).toBeInTheDocument()
    expect(mockGetMe).not.toHaveBeenCalled()
  })

  it('has no accessibility violations on the loaded profile', async () => {
    const { container } = renderWithRouter(<Profile />)
    await screen.findByRole('heading', { level: 1, name: 'ashketchum' })
    expect(await axe(container)).toHaveNoViolations()
  })
})
