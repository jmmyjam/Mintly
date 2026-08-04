import { useEffect, useState } from 'react'
import { getOAuthProviders, oauthLoginUrl } from '../api'
import styles from './SocialSignIn.module.css'

// Provider display metadata. Each icon is an inline SVG (no external requests —
// the app never loads a provider's script; sign-in is a plain server redirect).
const PROVIDERS: Record<string, { label: string; icon: React.ReactNode }> = {
  google: {
    label: 'Google',
    icon: (
      <svg viewBox="0 0 18 18" width="18" height="18" aria-hidden="true">
        <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z" />
        <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.02-3.7H.96v2.34A9 9 0 0 0 9 18z" />
        <path fill="#FBBC05" d="M3.98 10.72a5.4 5.4 0 0 1 0-3.44V4.94H.96a9 9 0 0 0 0 8.12l3.02-2.34z" />
        <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.9 11.42 0 9 0A9 9 0 0 0 .96 4.94l3.02 2.34C4.68 5.16 6.66 3.58 9 3.58z" />
      </svg>
    ),
  },
  microsoft: {
    label: 'Microsoft',
    icon: (
      <svg viewBox="0 0 18 18" width="18" height="18" aria-hidden="true">
        <path fill="#F25022" d="M0 0h8.5v8.5H0z" />
        <path fill="#7FBA00" d="M9.5 0H18v8.5H9.5z" />
        <path fill="#00A4EF" d="M0 9.5h8.5V18H0z" />
        <path fill="#FFB900" d="M9.5 9.5H18V18H9.5z" />
      </svg>
    ),
  },
}

// The social sign-in buttons (Google/Microsoft), shown on the Login page above
// the email/password form. Renders NOTHING when the backend has no provider
// configured, so the feature stays invisible until credentials are set. Each
// button is a full-page link to the provider start endpoint — not a fetch — so
// the browser follows the OAuth redirect chain itself.
export default function SocialSignIn() {
  const [providers, setProviders] = useState<string[] | null>(null)

  useEffect(() => {
    getOAuthProviders().then(setProviders)
  }, [])

  // Still loading, or none configured — render nothing (no empty divider).
  if (!providers || providers.length === 0) return null

  const known = providers.filter(p => p in PROVIDERS)
  if (known.length === 0) return null

  return (
    <div className={styles.wrap}>
      <div className={styles.buttons}>
        {known.map(p => (
          <a key={p} href={oauthLoginUrl(p)} className={styles.button}>
            <span className={styles.icon}>{PROVIDERS[p].icon}</span>
            <span>Continue with {PROVIDERS[p].label}</span>
          </a>
        ))}
      </div>
      <div className={styles.divider}>
        <span>or</span>
      </div>
    </div>
  )
}
