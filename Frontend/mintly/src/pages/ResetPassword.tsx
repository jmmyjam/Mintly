import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { errorMessage, forgotPassword, resetPassword } from '../api'
import styles from './ResetPassword.module.css'

// Mirrors the backend rules in auth.py so users get instant feedback
function passwordError(password: string): string | null {
  if (password.length < 8) return 'Password must be at least 8 characters'
  if (!/[A-Za-z]/.test(password)) return 'Password must contain at least one letter'
  if (!/\d/.test(password)) return 'Password must contain at least one number'
  return null
}

// One page, two modes: without ?token= it asks for the account email and sends
// the reset link; with ?token= (arriving from that email) it takes the new
// password. Each mode keeps its own state so switching can't leak messages.
export default function ResetPassword() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token')

  // Request-link mode
  const [email, setEmail] = useState('')
  const [sentMessage, setSentMessage] = useState('')
  const [requestError, setRequestError] = useState('')
  const [requesting, setRequesting] = useState(false)

  // New-password mode
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [resetError, setResetError] = useState('')
  const [resetting, setResetting] = useState(false)

  async function handleRequest(e: React.FormEvent) {
    e.preventDefault()
    if (requesting) return
    setRequestError('')
    setRequesting(true)
    try {
      setSentMessage(await forgotPassword(email.trim()))
    } catch (err) {
      setRequestError(errorMessage(err, 'Something went wrong. Please try again.'))
    } finally {
      setRequesting(false)
    }
  }

  async function handleReset(e: React.FormEvent) {
    e.preventDefault()
    if (resetting || !token) return
    setResetError('')
    const pwError = passwordError(newPw)
    if (pwError) { setResetError(pwError); return }
    if (newPw !== confirmPw) { setResetError('New passwords do not match'); return }
    setResetting(true)
    try {
      await resetPassword(token, newPw)
      navigate('/login', {
        state: { notice: 'Your password has been updated. Log in with your new password.' },
      })
    } catch (err) {
      setResetError(errorMessage(err, 'Something went wrong. Please try again.'))
      setResetting(false)
    }
  }

  return (
    <div className="page centered">
      <div className={styles.resetCard}>
        {token ? (
          <>
            <h1 className={styles.resetTitle}>Choose a new password</h1>
            <p className={styles.resetSubtitle}>
              At least 8 characters, with a letter and a number.
            </p>
            <form onSubmit={handleReset} className={styles.resetForm}>
              <input
                type="password"
                autoComplete="new-password"
                placeholder="New password"
                value={newPw}
                onChange={e => setNewPw(e.target.value)}
                required
                className={styles.formInput}
              />
              <input
                type="password"
                autoComplete="new-password"
                placeholder="Confirm new password"
                value={confirmPw}
                onChange={e => setConfirmPw(e.target.value)}
                required
                className={styles.formInput}
              />
              {resetError && (
                <p className="error">
                  {resetError}{' '}
                  {/* an invalid/expired link is fixed by requesting a fresh one */}
                  {resetError.includes('link') && (
                    <Link to="/reset-password">Request a new link</Link>
                  )}
                </p>
              )}
              <button type="submit" className="btn-primary" disabled={resetting}>
                {resetting ? 'Please wait...' : 'Set new password'}
              </button>
            </form>
          </>
        ) : (
          <>
            <h1 className={styles.resetTitle}>Reset your password</h1>
            <p className={styles.resetSubtitle}>
              Enter your account&apos;s email and we&apos;ll send you a reset link.
            </p>
            {sentMessage ? (
              <p className={styles.sentNote}>
                {sentMessage} The link works for 30 minutes. Check your spam
                folder if it doesn&apos;t arrive.
              </p>
            ) : (
              <form onSubmit={handleRequest} className={styles.resetForm}>
                <input
                  type="email"
                  autoComplete="email"
                  placeholder="Email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required
                  className={styles.formInput}
                />
                {requestError && <p className="error">{requestError}</p>}
                <button type="submit" className="btn-primary" disabled={requesting}>
                  {requesting ? 'Please wait...' : 'Send reset link'}
                </button>
              </form>
            )}
          </>
        )}
        <p className={styles.backRow}>
          <Link to="/login">Back to login</Link>
        </p>
      </div>
    </div>
  )
}
