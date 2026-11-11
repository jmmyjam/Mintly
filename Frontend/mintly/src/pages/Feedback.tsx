import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { errorMessage, getMe, getToken, submitFeedback } from '../api'
import styles from './Feedback.module.css'

const MAX_LENGTH = 2000

// Mirrors the backend checks in app/routers/feedback.py, same wording, so a
// mistake shows instantly instead of after a round trip
function feedbackError(message: string, email: string): string | null {
  if (message.trim().length < 10) return 'Please write at least 10 characters.'
  if ((message.match(/https?:\/\/|www\./gi) ?? []).length > 3) return 'Please include at most 3 links.'
  const at = email.trim()
  if (at && !(at.includes('@') && at.split('@').pop()!.includes('.'))) {
    return "That email address doesn't look right."
  }
  return null
}

// Public feedback form (route /feedback), open to signed-out visitors. The
// footer links here with ?from=<path> so a message arrives with the page it
// was about. Spam protection is server-side; the page's part is the hidden
// honeypot field and reporting how long the form was open.
export default function Feedback() {
  const [searchParams] = useSearchParams()
  const from = searchParams.get('from')
  const [message, setMessage] = useState('')
  const [email, setEmail] = useState('')
  const [website, setWebsite] = useState('')
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState('')
  const openedAt = useRef(0)

  useEffect(() => {
    openedAt.current = Date.now()
    if (!getToken()) return
    // Prefill the reply address for signed-in users, unless they've typed one
    getMe()
      .then(me => setEmail(prev => prev || me.email))
      .catch(() => {})
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (sending) return
    const invalid = feedbackError(message, email)
    if (invalid) { setError(invalid); return }
    setError('')
    setSending(true)
    try {
      setSent(await submitFeedback({
        message: message.trim(),
        email: email.trim() || null,
        page: from,
        website,
        elapsed_ms: Date.now() - openedAt.current,
      }))
    } catch (err) {
      setError(errorMessage(err, 'Something went wrong. Please try again.'))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="page centered">
      <div className={styles.feedbackCard}>
        <h1 className={styles.feedbackTitle}>Send feedback</h1>
        {sent ? (
          <div role="status">
            <p className={styles.sentNote}>{sent}</p>
            <p className={styles.sentNote}>
              We read every message. If you left an email, we&apos;ll reply there.
            </p>
            <p className={styles.backRow}><Link to={from || '/'}>Back to Mintly</Link></p>
          </div>
        ) : (
          <>
            <p className={styles.feedbackSubtitle}>
              Found a bug, a wrong price, or have an idea? Tell us. No account needed.
            </p>
            <form onSubmit={handleSubmit} className={styles.feedbackForm} noValidate>
              {/* The counter sits outside the label so it describes the field
                  rather than becoming part of its accessible name */}
              <div className={styles.field}>
                <label className={styles.field}>
                  <span className={styles.fieldLabel}>Your feedback</span>
                  <textarea
                    value={message}
                    onChange={e => setMessage(e.target.value)}
                    maxLength={MAX_LENGTH}
                    rows={7}
                    required
                    aria-describedby="feedback-count"
                    className={styles.formInput}
                  />
                </label>
                <span id="feedback-count" className={`${styles.count} num`}>
                  {message.length} / {MAX_LENGTH}
                </span>
              </div>
              <label className={styles.field}>
                <span className={styles.fieldLabel}>Email (optional, only if you want a reply)</span>
                <input
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  maxLength={254}
                  className={styles.formInput}
                />
              </label>
              {/* Honeypot: off-screen and skipped by keyboard and screen
                  readers, so only a form-filling bot ever puts text in it */}
              <div className={styles.honeypot} aria-hidden="true">
                <label>
                  Website
                  <input
                    type="text"
                    name="website"
                    tabIndex={-1}
                    autoComplete="off"
                    value={website}
                    onChange={e => setWebsite(e.target.value)}
                  />
                </label>
              </div>
              <div aria-live="polite">{error && <p className="error">{error}</p>}</div>
              <button type="submit" className="btn-primary" disabled={sending}>
                {sending ? 'Sending...' : 'Send feedback'}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
