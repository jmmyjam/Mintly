import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import SocialSignIn from './SocialSignIn'
import { getOAuthProviders } from '../api'
import { axe, renderWithRouter } from '../test/utils'

vi.mock('../api', () => ({
  getOAuthProviders: vi.fn(),
  oauthLoginUrl: (p: string) => `http://api.test/auth/oauth/${p}/start`,
}))
const mockProviders = vi.mocked(getOAuthProviders)

describe('SocialSignIn', () => {
  beforeEach(() => {
    mockProviders.mockReset()
  })

  it('renders nothing when no providers are configured', async () => {
    mockProviders.mockResolvedValue([])
    const { container } = renderWithRouter(<SocialSignIn />)
    await waitFor(() => expect(mockProviders).toHaveBeenCalled())
    expect(container.querySelector('a')).toBeNull()
    expect(screen.queryByText(/continue with/i)).not.toBeInTheDocument()
  })

  it('renders a button per configured provider pointing at its start URL', async () => {
    mockProviders.mockResolvedValue(['google', 'microsoft'])
    renderWithRouter(<SocialSignIn />)
    const google = await screen.findByRole('link', { name: /continue with google/i })
    expect(google).toHaveAttribute('href', 'http://api.test/auth/oauth/google/start')
    expect(screen.getByRole('link', { name: /continue with microsoft/i }))
      .toHaveAttribute('href', 'http://api.test/auth/oauth/microsoft/start')
  })

  it('ignores providers it has no display metadata for', async () => {
    mockProviders.mockResolvedValue(['google', 'myspace'])
    renderWithRouter(<SocialSignIn />)
    await screen.findByRole('link', { name: /continue with google/i })
    expect(screen.queryByText(/myspace/i)).not.toBeInTheDocument()
  })

  it('has no accessibility violations', async () => {
    mockProviders.mockResolvedValue(['google', 'microsoft'])
    const { container } = renderWithRouter(<SocialSignIn />)
    await screen.findByRole('link', { name: /continue with google/i })
    expect(await axe(container)).toHaveNoViolations()
  })
})
