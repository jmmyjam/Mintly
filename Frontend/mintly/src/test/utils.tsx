// Shared test helpers: render a component inside a router, and read back the
// current location so navigation can be asserted.
import type { ReactElement } from 'react'
import { render } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { configureAxe } from 'jest-axe'

// A shared axe runner for component-level checks. Two rules are turned off
// because they're page-level concerns that don't apply to a component rendered
// on its own: `region` wants all content inside a landmark (tested directly on
// Navbar/Footer, which ARE landmarks), and `color-contrast` can't be computed
// in jsdom, which does no layout or paint.
export const axe = configureAxe({
  rules: {
    region: { enabled: false },
    'color-contrast': { enabled: false },
  },
})

// A hidden probe that mirrors the active location into the DOM, so a test can
// assert where a click/submit navigated to.
export function LocationProbe() {
  const location = useLocation()
  return (
    <div data-testid="location">{location.pathname + location.search}</div>
  )
}

interface RouterOptions {
  route?: string
  withProbe?: boolean
}

// Render `ui` under a MemoryRouter (optionally starting at `route`), with a
// LocationProbe mounted when `withProbe` is set.
export function renderWithRouter(
  ui: ReactElement,
  { route = '/', withProbe = false }: RouterOptions = {},
) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      {ui}
      {withProbe && <LocationProbe />}
    </MemoryRouter>,
  )
}
