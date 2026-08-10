import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import Login from './Login'
import { login, register, getOAuthProviders } from '../api'
import { axe, renderWithRouter } from '../test/utils'

// Mocking ../api fully replaces the module, so every export the page (and the
// SocialSignIn / CardImage / DayChange it renders) touches must be present.
// errorMessage stays real-ish so a rejected login shows its Error message.
// getOAuthProviders drives SocialSignIn — default it to [] so those buttons
// stay out of the way; getCardImageUrl/oauthLoginUrl are plain helpers.
vi.mock('../api', () => ({
  login: vi.fn(),
  register: vi.fn(),
  getOAuthProviders: vi.fn(),
  oauthLoginUrl: (p: string) => `http://api.test/auth/oauth/${p}/start`,
  getCardImageUrl: (id: string) => `http://img.test/${id}.png`,
  errorMessage: (err: unknown, fallback: string) =>
    err instanceof Error && err.message ? err.message : fallback,
}))
const mockLogin = vi.mocked(login)
const mockRegister = vi.mocked(register)
const mockProviders = vi.mocked(getOAuthProviders)

// Renders Login under a router that carries router-state (session-expired notice,
// register: true), which renderWithRouter's string route can't express.
function renderLoginWithState(state: unknown) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/login', state }]}>
      <Login />
    </MemoryRouter>,
  )
}

// Flushes SocialSignIn's getOAuthProviders().then(setProviders) microtask so a
// state update never lands outside act.
async function settle() {
  await screen.findByRole('heading', { level: 1 })
  await waitFor(() => expect(mockProviders).toHaveBeenCalled())
}

beforeEach(() => {
  mockLogin.mockReset()
  mockRegister.mockReset()
  mockProviders.mockReset()
  mockProviders.mockResolvedValue([])
})

describe('Login page — tabs', () => {
  it('opens on the Log in tab by default', async () => {
    renderWithRouter(<Login />, { route: '/login' })
    await settle()
    expect(screen.getByRole('heading', { level: 1, name: 'Welcome back' })).toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
    // email + terms are register-only
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('reveals the email field, Terms checkbox and strength meter on the Register tab', async () => {
    const user = userEvent.setup()
    renderWithRouter(<Login />, { route: '/login' })
    await settle()
    await user.click(screen.getByRole('button', { name: 'Register' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Create your account' })).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    expect(
      screen.getByRole('checkbox', { name: /I agree to the Terms of Service/ }),
    ).toBeInTheDocument()
    // the strength meter's description doubles as the password field's aria-describedby
    expect(screen.getByText('At least 8 characters, with a letter and a number')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Create a password')).toHaveAttribute(
      'aria-describedby',
      'pw-strength-desc',
    )
  })

  it('opens on the Register tab when navigated with state.register', async () => {
    renderLoginWithState({ register: true })
    await settle()
    expect(screen.getByRole('heading', { level: 1, name: 'Create your account' })).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
  })

  it('switches to Register from the "Create a free account" link under the form', async () => {
    const user = userEvent.setup()
    renderWithRouter(<Login />, { route: '/login' })
    await settle()
    await user.click(screen.getByRole('button', { name: 'Create a free account' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Create your account' })).toBeInTheDocument()
  })
})

describe('Login page — login submit', () => {
  it('calls login and navigates to /portfolio on success', async () => {
    mockLogin.mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderWithRouter(<Login />, { route: '/login', withProbe: true })
    await settle()
    await user.type(screen.getByLabelText('Username'), 'ash')
    await user.type(screen.getByPlaceholderText('Enter your password'), 'secret123{Enter}')
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/portfolio'))
    expect(mockLogin).toHaveBeenCalledWith('ash', 'secret123')
    expect(mockRegister).not.toHaveBeenCalled()
  })

  it('shows the error message when login fails', async () => {
    mockLogin.mockRejectedValue(new Error('Invalid username or password'))
    const user = userEvent.setup()
    renderWithRouter(<Login />, { route: '/login', withProbe: true })
    await settle()
    await user.type(screen.getByLabelText('Username'), 'ash')
    await user.type(screen.getByPlaceholderText('Enter your password'), 'wrongpass{Enter}')
    expect(await screen.findByText('Invalid username or password')).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/login')
  })
})

describe('Login page — register submit', () => {
  it('registers then logs in and navigates on success', async () => {
    mockRegister.mockResolvedValue(undefined)
    mockLogin.mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderWithRouter(<Login />, { route: '/login', withProbe: true })
    await settle()
    await user.click(screen.getByRole('button', { name: 'Register' }))
    await user.type(screen.getByLabelText('Email'), 'ash@example.com')
    await user.type(screen.getByLabelText('Username'), 'ash')
    await user.type(screen.getByPlaceholderText('Create a password'), 'password1')
    await user.click(screen.getByRole('checkbox', { name: /I agree to the Terms of Service/ }))
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/portfolio'))
    expect(mockRegister).toHaveBeenCalledWith('ash@example.com', 'ash', 'password1', true)
    expect(mockLogin).toHaveBeenCalledWith('ash', 'password1')
  })

  it('blocks a weak password client-side without calling register', async () => {
    const user = userEvent.setup()
    renderWithRouter(<Login />, { route: '/login' })
    await settle()
    await user.click(screen.getByRole('button', { name: 'Register' }))
    await user.type(screen.getByLabelText('Email'), 'ash@example.com')
    await user.type(screen.getByLabelText('Username'), 'ash')
    await user.type(screen.getByPlaceholderText('Create a password'), 'abc')
    await user.click(screen.getByRole('checkbox', { name: /I agree to the Terms of Service/ }))
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(screen.getByText('Password must be at least 8 characters')).toBeInTheDocument()
    expect(mockRegister).not.toHaveBeenCalled()
  })

  it('requires agreeing to the Terms before registering', async () => {
    const user = userEvent.setup()
    renderWithRouter(<Login />, { route: '/login' })
    await settle()
    await user.click(screen.getByRole('button', { name: 'Register' }))
    await user.type(screen.getByLabelText('Email'), 'ash@example.com')
    await user.type(screen.getByLabelText('Username'), 'ash')
    await user.type(screen.getByPlaceholderText('Create a password'), 'password1')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(screen.getByText('You must agree to the Terms of Service')).toBeInTheDocument()
    expect(mockRegister).not.toHaveBeenCalled()
  })
})

describe('Login page — router-state notices and OAuth errors', () => {
  it('shows the session-expired notice from router state', async () => {
    renderLoginWithState({ notice: 'Your session expired. Please log in again.' })
    await settle()
    expect(screen.getByText('Your session expired. Please log in again.')).toBeInTheDocument()
  })

  it('shows the logged-out notice from router state', async () => {
    renderLoginWithState({ notice: "You've been logged out successfully." })
    await settle()
    expect(screen.getByText("You've been logged out successfully.")).toBeInTheDocument()
  })

  it('maps ?oauth_error=cancelled to a user-facing message', async () => {
    renderWithRouter(<Login />, { route: '/login?oauth_error=cancelled' })
    await settle()
    expect(screen.getByText('Sign-in was cancelled.')).toBeInTheDocument()
  })

  it('has no accessibility violations', async () => {
    const { container } = renderWithRouter(<Login />, { route: '/login' })
    await settle()
    expect(await axe(container)).toHaveNoViolations()
  })
})
