import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { addToWatchlist, errorMessage, getToken, SessionExpiredError } from '../api'
import { useSessionRedirect } from '../hooks'
import StatusMessage from './StatusMessage'
import styles from './WatchButton.module.css'

// The "watch this card" entry point on CardDetail: a light outline button that
// expands to an optional price-target + direction, then POSTs to the watchlist
// (an upsert — safe to click again). Managing/editing a watch happens on the
// Watchlist page; this only adds. Signed-out clicks bounce to /login, like the
// add-to-portfolio flow.
export default function WatchButton({ cardId }: { cardId: string }) {
  const navigate = useNavigate()
  const redirectToLogin = useSessionRedirect()
  const [open, setOpen] = useState(false)
  const [target, setTarget] = useState('')
  const [direction, setDirection] = useState<'below' | 'above'>('below')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [added, setAdded] = useState(false)

  function start() {
    if (!getToken()) {
      navigate('/login')
      return
    }
    setError('')
    setOpen(true)
  }

  async function submit() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const raw = target.trim()
      const parsed = raw === '' ? null : parseFloat(raw)
      const targetPrice = parsed != null && !Number.isNaN(parsed) && parsed >= 0 ? parsed : null
      await addToWatchlist(cardId, targetPrice, direction)
      setOpen(false)
      setAdded(true)
    } catch (err: unknown) {
      if (err instanceof SessionExpiredError) {
        redirectToLogin()
        return
      }
      setError(errorMessage(err, "We couldn't update your watchlist. Please try again."))
    } finally {
      setBusy(false)
    }
  }

  if (added) {
    return (
      <p className={styles.done}>
        <span aria-hidden="true">★</span> On your watchlist.{' '}
        <Link to="/watchlist">Manage alerts</Link>
      </p>
    )
  }

  if (!open) {
    return (
      <button type="button" className={`btn-outline btn-sm ${styles.trigger}`} onClick={start}>
        ☆ Watch this card
      </button>
    )
  }

  return (
    <div className={styles.form}>
      <p className={styles.hint}>Email me when the price is</p>
      <div className={styles.row}>
        <select
          className="filter-select"
          value={direction}
          onChange={e => setDirection(e.target.value as 'below' | 'above')}
          aria-label="Alert direction"
        >
          <option value="below">below</option>
          <option value="above">above</option>
        </select>
        <span className={styles.price}>
          <span aria-hidden="true">$</span>
          <input
            type="number"
            inputMode="decimal"
            min="0"
            step="0.01"
            value={target}
            onChange={e => setTarget(e.target.value)}
            placeholder="any"
            aria-label="Target price"
            className={styles.input}
          />
        </span>
      </div>
      <p className={styles.note}>Leave the price blank to just track it, with no email.</p>
      {error && <StatusMessage ok={false}>{error}</StatusMessage>}
      <div className={styles.actions}>
        <button type="button" className="btn-primary btn-sm" onClick={submit} disabled={busy}>
          {busy ? 'Saving…' : 'Add to watchlist'}
        </button>
        <button type="button" className="btn-outline btn-sm" onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
      </div>
    </div>
  )
}
