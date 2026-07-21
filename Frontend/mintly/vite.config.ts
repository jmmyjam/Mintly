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
})
