/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  css: {
    // Let *.module.css keep kebab-case class names while components read them
    // as clean camelCase (styles.footerInner for .footer-inner).
    modules: { localsConvention: 'camelCase' },
  },
  // Vitest — `vite build` ignores this block. Tests run under jsdom with RTL +
  // jest-axe; see src/test/setup.ts. CSS Modules aren't processed for tests
  // (class-name assertions are avoided on purpose), which keeps runs fast.
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: false,
    // clearMocks resets call history between tests (needed for the vi.fn() mocks
    // created in vi.mock factories); restoreMocks puts spied-on methods back.
    clearMocks: true,
    restoreMocks: true,
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
