import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import Accessibility from './Accessibility'
import { setSettings } from '../accessibility'
import { axe } from '../test/utils'

beforeEach(() => {
  localStorage.clear()
  setSettings({ reduceMotion: false, highContrast: false, underlineLinks: false, textSize: 'default' })
})

describe('Accessibility page', () => {
  it('states the page heading and the WCAG 2.1 AA target', () => {
    render(<Accessibility />)
    expect(screen.getByRole('heading', { level: 1, name: 'Accessibility' })).toBeInTheDocument()
    expect(screen.getByText(/WCAG.*2\.1.*Level AA/i)).toBeInTheDocument()
  })

  it('embeds the display-preference controls so they work without an account', () => {
    render(<Accessibility />)
    expect(screen.getByRole('switch', { name: 'Reduce motion' })).toBeInTheDocument()
    expect(screen.getByRole('radiogroup', { name: 'Text size' })).toBeInTheDocument()
  })

  it('offers a contact method for reporting barriers', () => {
    render(<Accessibility />)
    expect(screen.getByRole('link', { name: 'mintlytcg@gmail.com' })).toHaveAttribute(
      'href',
      'mailto:mintlytcg@gmail.com',
    )
  })

  it('has no accessibility violations', async () => {
    const { container } = render(<Accessibility />)
    expect(await axe(container)).toHaveNoViolations()
  })
})
