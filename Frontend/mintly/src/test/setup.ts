// Vitest global setup — runs once before the test files (see vite.config.ts).
import { afterEach, expect } from 'vitest'
import { cleanup } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { toHaveNoViolations } from 'jest-axe'

// jest-axe ships the matcher; register it on Vitest's expect so tests can call
// `expect(await axe(container)).toHaveNoViolations()`.
expect.extend(toHaveNoViolations)

// Unmount anything a test rendered so the next test starts from a clean DOM.
afterEach(() => {
  cleanup()
})

// Node ships an experimental global `localStorage` that shadows jsdom's and is
// inert without --localstorage-file (its methods throw). Install a clean
// in-memory Storage so the a11y prefs + auth token round-trip deterministically.
function createMemoryStorage(): Storage {
  let store = new Map<string, string>()
  return {
    get length() {
      return store.size
    },
    clear() {
      store = new Map()
    },
    getItem(key: string) {
      return store.has(key) ? (store.get(key) as string) : null
    },
    key(index: number) {
      return [...store.keys()][index] ?? null
    },
    removeItem(key: string) {
      store.delete(key)
    },
    setItem(key: string, value: string) {
      store.set(key, String(value))
    },
  } as unknown as Storage
}

const memoryStorage = createMemoryStorage()
Object.defineProperty(globalThis, 'localStorage', { value: memoryStorage, writable: true, configurable: true })
if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'localStorage', { value: memoryStorage, writable: true, configurable: true })
}

// jsdom doesn't implement these, but components (Navbar scroll chrome, recharts
// containers, reduce-motion checks) reach for them — stub them so nothing throws.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList
}

if (!window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

if (!window.scrollTo) {
  window.scrollTo = () => {}
}
