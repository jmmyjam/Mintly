import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import Terms from './Terms'
import Privacy from './Privacy'
import { axe } from '../test/utils'

// The static legal pages are pure content (no router links), so they render on
// their own; each gets an axe pass plus a top-heading sanity check.
describe('legal pages accessibility', () => {
  it('Terms has a single h1 and no accessibility violations', async () => {
    const { container } = render(<Terms />)
    expect(screen.getByRole('heading', { level: 1, name: 'Terms of Service' })).toBeInTheDocument()
    expect(await axe(container)).toHaveNoViolations()
  })

  it('Privacy has a single h1 and no accessibility violations', async () => {
    const { container } = render(<Privacy />)
    expect(screen.getByRole('heading', { level: 1, name: 'Privacy Policy' })).toBeInTheDocument()
    expect(await axe(container)).toHaveNoViolations()
  })
})
