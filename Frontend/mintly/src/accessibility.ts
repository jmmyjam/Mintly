import { useSyncExternalStore } from 'react'

// ----- Accessibility preferences ------------------------------------------------
//
// Device-local display settings the user controls from the Profile page. They're
// applied as data-* attributes on <html>, which the CSS in index.css reacts to
// (reduce motion / high contrast / underline links / text size). Kept out of the
// backend on purpose — they're personal to the browser, not account data — so
// they persist in localStorage and take effect instantly with no round-trip.

export type TextSize = 'default' | 'large' | 'larger'

export interface A11ySettings {
  reduceMotion: boolean
  highContrast: boolean
  underlineLinks: boolean
  textSize: TextSize
}

const DEFAULTS: A11ySettings = {
  reduceMotion: false,
  highContrast: false,
  underlineLinks: false,
  textSize: 'default',
}

const STORAGE_KEY = 'mintly-a11y'

function load(): A11ySettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    // Spread over DEFAULTS so a settings shape added later still loads cleanly
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) }
  } catch {
    /* corrupt/unavailable storage — fall back to defaults */
  }
  return { ...DEFAULTS }
}

// Mirror the settings onto <html> so plain CSS can style off them. Called at
// import time (below) so preferences apply before first paint — no flash.
function applyToDocument(s: A11ySettings) {
  const root = document.documentElement
  toggleAttr(root, 'data-reduce-motion', s.reduceMotion)
  toggleAttr(root, 'data-contrast', s.highContrast, 'high')
  toggleAttr(root, 'data-underline-links', s.underlineLinks)
  if (s.textSize === 'default') root.removeAttribute('data-text-size')
  else root.setAttribute('data-text-size', s.textSize)
}

function toggleAttr(el: HTMLElement, name: string, on: boolean, value = 'true') {
  if (on) el.setAttribute(name, value)
  else el.removeAttribute(name)
}

let current = load()
const listeners = new Set<() => void>()

applyToDocument(current)

function getSnapshot(): A11ySettings {
  return current
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function setSettings(patch: Partial<A11ySettings>) {
  current = { ...current, ...patch }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(current))
  } catch {
    /* storage full/blocked — the in-memory setting still applies this session */
  }
  applyToDocument(current)
  listeners.forEach(l => l())
}

// Shared, subscription-backed access (useSyncExternalStore keeps every consumer —
// Navbar, HeroSearch, Profile — in sync without a synchronous setState in effect)
export function useAccessibility() {
  const settings = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
  return { settings, update: setSettings }
}
