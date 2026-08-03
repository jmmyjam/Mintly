import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { errorMessage, verifyEmail } from '../api'
import styles from './VerifyEmail.module.css'

// Landing page for the link in the verification email (route /verify-email?token=).
// Unauthed on purpose — it works whether or not this browser is logged in. It
// confirms the token against the backend once on mount and reports the outcome.
export default function VerifyEmail() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  // Seed status from the token's presence so the no-token case needs no effect
  // setState (keeps the strict react-hooks lint happy).
  const [status, setStatus] = useState<'verifying' | 'success' | 'error'>(
    token ? 'verifying' : 'error',
  )
  const [message, setMessage] = useState(
    token ? '' : 'This verification link is missing its token.',
  )

  useEffect(() => {
    if (!token) return
    let active = true
    verifyEmail(token)
      .then(() => { if (active) setStatus('success') })
      .catch(err => {
        if (!active) return
        setStatus('error')
        setMessage(errorMessage(err, "We couldn't verify your email. The link may have expired."))
      })
    return () => { active = false }
  }, [token])

  return (
    <div className="page centered">
      <div className={styles.card}>
        {status === 'verifying' && (
          <>
            <h1 className={styles.title}>Verifying your email...</h1>
            <p className={styles.subtitle}>One moment while we confirm your address.</p>
          </>
        )}
        {status === 'success' && (
          <>
            <h1 className={styles.title}>Email verified</h1>
            <p className={styles.subtitle}>
              Thanks, your email address is confirmed. You&apos;re all set.
            </p>
            <p className={styles.note}>
              <Link to="/portfolio">Go to your portfolio</Link>
            </p>
          </>
        )}
        {status === 'error' && (
          <>
            <h1 className={styles.title}>Verification failed</h1>
            <p className={styles.subtitle}>{message}</p>
            <p className={styles.note}>
              You can request a fresh link from your profile once you&apos;re logged in.
            </p>
          </>
        )}
        <p className={styles.backRow}>
          <Link to="/login">Back to login</Link>
        </p>
      </div>
    </div>
  )
}
