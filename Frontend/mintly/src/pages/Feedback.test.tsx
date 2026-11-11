import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Feedback from './Feedback'
import { getMe, getToken, submitFeedback, type UserProfile } from '../api'
import { axe, renderWithRouter } from '../test/utils'

vi.mock('../api', async (importActual) => {
  const actual = await importActual<typeof import('../api')>()
  return {
    ...actual,
    submitFeedback: vi.fn(),
    getMe: vi.fn(),
    getToken: vi.fn(),
  }
})
const mockSubmit = vi.mocked(submitFeedback)
const mockGetMe = vi.mocked(getMe)
const mockGetToken = vi.mocked(getToken)

const MESSAGE = 'The scanner keeps missing my Japanese cards.'

beforeEach(() => {
  mockSubmit.mockReset()
  mockSubmit.mockResolvedValue('Thanks! Your feedback was sent.')
  mockGetToken.mockReturnValue(null)
  mockGetMe.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('Feedback', () => {
  it('renders labeled fields and no account prompt', () => {
    renderWithRouter(<Feedback />, { route: '/feedback' })
    expect(screen.getByRole('heading', { level: 1, name: 'Send feedback' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Your feedback' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: /Email \(optional/ })).toBeInTheDocument()
    expect(screen.getByText('0 / 2000')).toBeInTheDocument()
  })

  it('keeps the honeypot out of the accessibility tree', () => {
    renderWithRouter(<Feedback />, { route: '/feedback' })
    expect(screen.queryByRole('textbox', { name: 'Website' })).not.toBeInTheDocument()
  })

  it('submits the message, page, honeypot and time on form, then thanks the user', async () => {
    const user = userEvent.setup()
    renderWithRouter(<Feedback />, { route: '/feedback?from=%2Fscan' })
    await user.type(screen.getByRole('textbox', { name: 'Your feedback' }), MESSAGE)
    await user.type(screen.getByRole('textbox', { name: /Email/ }), 'misty@example.com')
    await user.click(screen.getByRole('button', { name: 'Send feedback' }))

    expect(mockSubmit).toHaveBeenCalledOnce()
    const body = mockSubmit.mock.calls[0][0]
    expect(body).toMatchObject({
      message: MESSAGE, email: 'misty@example.com', page: '/scan', website: '',
    })
    expect(body.elapsed_ms).toBeGreaterThanOrEqual(0)
    expect(await screen.findByText('Thanks! Your feedback was sent.')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Your feedback' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to Mintly' })).toHaveAttribute('href', '/scan')
  })

  it('sends a null email when left blank', async () => {
    const user = userEvent.setup()
    renderWithRouter(<Feedback />, { route: '/feedback' })
    await user.type(screen.getByRole('textbox', { name: 'Your feedback' }), MESSAGE)
    await user.click(screen.getByRole('button', { name: 'Send feedback' }))
    expect(mockSubmit.mock.calls[0][0]).toMatchObject({ email: null, page: null })
  })

  it('blocks a too-short message client-side with the backend wording', async () => {
    const user = userEvent.setup()
    renderWithRouter(<Feedback />, { route: '/feedback' })
    await user.type(screen.getByRole('textbox', { name: 'Your feedback' }), 'hi')
    await user.click(screen.getByRole('button', { name: 'Send feedback' }))
    expect(screen.getByText('Please write at least 10 characters.')).toBeInTheDocument()
    expect(mockSubmit).not.toHaveBeenCalled()
  })

  it('blocks link spam client-side', async () => {
    const user = userEvent.setup()
    renderWithRouter(<Feedback />, { route: '/feedback' })
    await user.type(
      screen.getByRole('textbox', { name: 'Your feedback' }),
      'see http://a.co http://b.co http://c.co http://d.co',
    )
    await user.click(screen.getByRole('button', { name: 'Send feedback' }))
    expect(screen.getByText('Please include at most 3 links.')).toBeInTheDocument()
    expect(mockSubmit).not.toHaveBeenCalled()
  })

  it('surfaces a server error (e.g. the rate limit) and keeps the form', async () => {
    mockSubmit.mockRejectedValue(new Error('Too many feedback messages. Try again in about 300 seconds.'))
    const user = userEvent.setup()
    renderWithRouter(<Feedback />, { route: '/feedback' })
    await user.type(screen.getByRole('textbox', { name: 'Your feedback' }), MESSAGE)
    await user.click(screen.getByRole('button', { name: 'Send feedback' }))
    expect(
      await screen.findByText('Too many feedback messages. Try again in about 300 seconds.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Your feedback' })).toHaveValue(MESSAGE)
  })

  it('prefills the reply email for a signed-in user', async () => {
    mockGetToken.mockReturnValue('token')
    mockGetMe.mockResolvedValue({ email: 'ash@example.com' } as UserProfile)
    renderWithRouter(<Feedback />, { route: '/feedback' })
    expect(await screen.findByDisplayValue('ash@example.com')).toBeInTheDocument()
  })

  it('has no accessibility violations', async () => {
    const { container } = renderWithRouter(<Feedback />, { route: '/feedback' })
    expect(await axe(container)).toHaveNoViolations()
  })
})
