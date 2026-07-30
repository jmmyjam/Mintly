// Teach Vitest's `expect` about jest-axe's matcher (registered at runtime in
// setup.ts). Mirrors Vitest's documented "extending matchers" pattern.
import 'vitest'

interface AxeMatchers<R = unknown> {
  toHaveNoViolations(): R
}

declare module 'vitest' {
  // eslint-disable-next-line @typescript-eslint/no-empty-object-type
  interface Matchers<T = any> extends AxeMatchers<T> {}
}
