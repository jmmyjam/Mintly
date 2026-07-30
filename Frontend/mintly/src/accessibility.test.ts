import { describe, it, expect, beforeEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { setSettings, useAccessibility } from './accessibility'

const root = document.documentElement

// The store is module-level state, so reset it (and storage) before each test.
beforeEach(() => {
  localStorage.clear()
  setSettings({
    reduceMotion: false,
    highContrast: false,
    underlineLinks: false,
    textSize: 'default',
  })
})

describe('setSettings', () => {
  it('persists the merged settings to localStorage', () => {
    setSettings({ reduceMotion: true })
    const stored = JSON.parse(localStorage.getItem('mintly-a11y') ?? '{}')
    expect(stored.reduceMotion).toBe(true)
    expect(stored.textSize).toBe('default')
  })

  it('mirrors reduce-motion onto <html> as a data attribute, and clears it when off', () => {
    setSettings({ reduceMotion: true })
    expect(root.getAttribute('data-reduce-motion')).toBe('true')
    setSettings({ reduceMotion: false })
    expect(root.hasAttribute('data-reduce-motion')).toBe(false)
  })

  it('sets high contrast as data-contrast="high"', () => {
    setSettings({ highContrast: true })
    expect(root.getAttribute('data-contrast')).toBe('high')
    setSettings({ highContrast: false })
    expect(root.hasAttribute('data-contrast')).toBe(false)
  })

  it('sets underline-links', () => {
    setSettings({ underlineLinks: true })
    expect(root.getAttribute('data-underline-links')).toBe('true')
  })

  it('reflects a non-default text size but removes the attribute for default', () => {
    setSettings({ textSize: 'larger' })
    expect(root.getAttribute('data-text-size')).toBe('larger')
    setSettings({ textSize: 'default' })
    expect(root.hasAttribute('data-text-size')).toBe(false)
  })
})

describe('useAccessibility', () => {
  it('exposes the current settings and updates every consumer', () => {
    const { result } = renderHook(() => useAccessibility())
    expect(result.current.settings.highContrast).toBe(false)

    act(() => result.current.update({ highContrast: true }))

    expect(result.current.settings.highContrast).toBe(true)
    expect(root.getAttribute('data-contrast')).toBe('high')
  })
})
