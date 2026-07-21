import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { login, register, getCardImageUrl } from '../api'
import type { PriceChange } from '../api'
import { money } from '../format'
import CardImage from '../components/CardImage'
import DayChange from '../components/DayChange'
import styles from './Login.module.css'

// Mirrors the backend rules in auth.py so users get instant feedback
function passwordError(password: string): string | null {
  if (password.length < 8) return 'Password must be at least 8 characters'
  if (!/[A-Za-z]/.test(password)) return 'Password must contain at least one letter'
  if (!/\d/.test(password)) return 'Password must contain at least one number'
  return null
}

// Illustrative-only preview shown beside the form (marked "Example" and
// aria-hidden): a taste of what the portfolio looks like, with real Base Set
// card art but sample prices/changes — there's no real account to read when
// logged out. The card rows and chips reuse the same DayChange / CardImage
// components as the live app, so the preview matches the real UI exactly.
const SINCE_DAY = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10)
const SINCE_MONTH = new Date(Date.now() - 30 * 86_400_000).toISOString().slice(0, 10)

const PREVIEW: {
  value: number
  change: PriceChange
  holdings: { id: string; name: string; price: number; change: PriceChange }[]
} = {
  value: 4820,
  change: { amount: 531.4, percent: 12.4, since: SINCE_MONTH },
  holdings: [
    { id: 'base1-4', name: 'Charizard', price: 412, change: { amount: 12.4, percent: 3.1, since: SINCE_DAY } },
    { id: 'base1-2', name: 'Blastoise', price: 203, change: { amount: 1.61, percent: 0.8, since: SINCE_DAY } },
    { id: 'base1-15', name: 'Venusaur', price: 176, change: { amount: -2.14, percent: -1.2, since: SINCE_DAY } },
    { id: 'base1-58', name: 'Pikachu', price: 88, change: { amount: 2.06, percent: 2.4, since: SINCE_DAY } },
  ],
}

export default function Login() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [agreedToTerms, setAgreedToTerms] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  // e.g. "Your session expired — please log in again." when redirected here on a 401
  const notice = (location.state as { notice?: string } | null)?.notice

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (mode === 'register') {
      const pwError = passwordError(password)
      if (pwError) {
        setError(pwError)
        return
      }
      // Mirrors the backend rule in auth.py, with the identical message
      if (!agreedToTerms) {
        setError('You must agree to the Terms of Service')
        return
      }
    }
    setLoading(true)
    try {
      if (mode === 'register') {
        await register(email, username, password, agreedToTerms)
      }
      await login(username, password)
      navigate('/portfolio')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  function switchMode(next: 'login' | 'register') {
    setMode(next)
    setError('')
    setEmail('')
    setUsername('')
    setPassword('')
    setAgreedToTerms(false)
  }

  return (
    <div className="page centered">
      <div className={styles.authLayout}>
      <div className={styles.authCard}>
        <div className={styles.authIntro}>
          <h1 className={styles.authTitle}>
            {mode === 'login' ? 'Welcome back' : 'Create your account'}
          </h1>
          <p className={styles.authSubtitle}>
            {mode === 'login'
              ? 'Log in to track your collection.'
              : 'Start tracking your portfolio today.'}
          </p>
        </div>
        <div className={styles.authTabs}>
          <button type="button" className={`${styles.tab} ${mode === 'login' ? styles.active : ''}`} onClick={() => switchMode('login')}>
            Login
          </button>
          <button type="button" className={`${styles.tab} ${mode === 'register' ? styles.active : ''}`} onClick={() => switchMode('register')}>
            Register
          </button>
        </div>

        {notice && !error && <p className={styles.formHint}>{notice}</p>}

        <form onSubmit={handleSubmit} className={styles.authForm}>
          {mode === 'register' && (
            <input
              type="email"
              name="email"
              autoComplete="email"
              placeholder="Email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              className={styles.formInput}
            />
          )}
          <input
            type="text"
            name="username"
            autoComplete="username"
            placeholder="Username"
            value={username}
            onChange={e => setUsername(e.target.value)}
            required
            className={styles.formInput}
          />
          <input
            type="password"
            name="password"
            // login reads an existing password, register creates one — the
            // right hint lets password managers autofill/submit cleanly
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            placeholder="Password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            className={styles.formInput}
          />
          {mode === 'login' && (
            <p className={styles.forgotRow}>
              <Link to="/reset-password" className={styles.forgotLink}>Forgot password?</Link>
            </p>
          )}
          {mode === 'register' && (
            <p className={styles.formHint}>At least 8 characters, with a letter and a number.</p>
          )}
          {mode === 'register' && (
            <label className={styles.termsRow}>
              <input
                type="checkbox"
                checked={agreedToTerms}
                onChange={e => setAgreedToTerms(e.target.checked)}
              />
              <span>
                I agree to the <Link to="/terms">Terms of Service</Link> and{' '}
                <Link to="/privacy">Privacy Policy</Link>
              </span>
            </label>
          )}
          {error && <p className="error">{error}</p>}
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? 'Please wait...' : mode === 'login' ? 'Login' : 'Create Account'}
          </button>
        </form>
      </div>

      {/* Illustrative preview — decorative sample data, hidden from screen
          readers and dropped on narrow screens so the form stays the focus */}
      <aside className={styles.preview} aria-hidden="true">
        <div className={styles.previewHead}>
          <span className={styles.previewLabel}>Portfolio value</span>
          <span className={styles.exampleTag}>Example</span>
        </div>
        <div className={styles.previewValueRow}>
          <span className={styles.previewValue}>{money(PREVIEW.value)}</span>
          <DayChange change={PREVIEW.change} />
        </div>
        <svg className={styles.spark} viewBox="0 0 240 46" preserveAspectRatio="none">
          <path
            d="M4,36 L30,33 L56,35 L82,26 L108,29 L134,19 L160,22 L186,12 L212,14 L236,7 L236,46 L4,46 Z"
            fill="var(--accent-bg)"
          />
          <path
            d="M4,36 L30,33 L56,35 L82,26 L108,29 L134,19 L160,22 L186,12 L212,14 L236,7"
            fill="none"
            stroke="var(--accent)"
            strokeWidth="2"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          <circle cx="236" cy="7" r="3.5" fill="var(--accent)" />
        </svg>
        <ul className={styles.holdings}>
          {PREVIEW.holdings.map(h => (
            <li className={styles.holding} key={h.id}>
              <span className={styles.thumb}>
                <CardImage src={getCardImageUrl(h.id)} alt={h.name} size="tile" />
              </span>
              <span className={styles.holdingName}>{h.name}</span>
              <span className={styles.holdingPrice}>{money(h.price)}</span>
              <DayChange change={h.change} />
            </li>
          ))}
        </ul>
      </aside>
      </div>
    </div>
  )
}
