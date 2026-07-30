import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AccessibilitySettings from './AccessibilitySettings'
import { setSettings } from '../accessibility'
import { axe } from '../test/utils'

const root = document.documentElement

beforeEach(() => {
  localStorage.clear()
  setSettings({ reduceMotion: false, highContrast: false, underlineLinks: false, textSize: 'default' })
})

describe('AccessibilitySettings', () => {
  it('renders the three preference switches and a text-size radio group', () => {
    render(<AccessibilitySettings />)
    expect(screen.getByRole('switch', { name: 'Reduce motion' })).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'High contrast' })).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Underline links' })).toBeInTheDocument()
    expect(screen.getByRole('radiogroup', { name: 'Text size' })).toBeInTheDocument()
  })

  it('reflects the stored state and toggles a switch on click (updating <html>)', async () => {
    const user = userEvent.setup()
    render(<AccessibilitySettings />)
    const highContrast = screen.getByRole('switch', { name: 'High contrast' })
    expect(highContrast).not.toBeChecked()

    await user.click(highContrast)

    expect(highContrast).toBeChecked()
    expect(root.getAttribute('data-contrast')).toBe('high')
  })

  it('selects a text size and mirrors it onto <html>', async () => {
    const user = userEvent.setup()
    render(<AccessibilitySettings />)
    expect(screen.getByRole('radio', { name: 'Default' })).toBeChecked()

    await user.click(screen.getByRole('radio', { name: 'Larger' }))

    expect(screen.getByRole('radio', { name: 'Larger' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Default' })).not.toBeChecked()
    expect(root.getAttribute('data-text-size')).toBe('larger')
  })

  it('has no accessibility violations', async () => {
    const { container } = render(<AccessibilitySettings />)
    expect(await axe(container)).toHaveNoViolations()
  })
})
