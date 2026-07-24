import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CONNECTION_ERROR, deleteAccount, SessionExpiredError } from '../api'
import { useSessionRedirect } from '../hooks'
import StatusMessage from './StatusMessage'
import styles from './DeleteAccount.module.css'

// Profile-page "danger zone": permanently delete the account and all its
// portfolio data. Two-step, with a typed "DELETE" gate proportionate to how
// irreversible this is (the app's convention: no native confirm()/alert()).
export default function DeleteAccount() {
  const navigate = useNavigate()
  const redirectToLogin = useSessionRedirect()
  const [open, setOpen] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const canDelete = confirmText.trim().toUpperCase() === 'DELETE'

  async function handleDelete() {
    if (!canDelete || busy) return
    setBusy(true)
    setError('')
    try {
      await deleteAccount()
      navigate('/login', {
        state: { notice: 'Your account and all its data have been deleted.' },
      })
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        redirectToLogin()
        return
      }
      setError(
        err instanceof TypeError
          ? CONNECTION_ERROR
          : "We couldn't delete your account. Please try again.",
      )
      setBusy(false)
    }
  }

  function cancel() {
    setOpen(false)
    setConfirmText('')
    setError('')
  }

  return (
    <section className={styles.dangerZone} aria-label="Account settings">
      <h2 className={styles.dangerTitle}>Delete account</h2>
      {!open ? (
        <>
          <p className={styles.dangerText}>
            Permanently delete your account and everything in your portfolio.
            This can't be undone.
          </p>
          <button className="btn-outline btn-sm btn-danger" onClick={() => setOpen(true)}>
            Delete account
          </button>
        </>
      ) : (
        <>
          <p className={styles.dangerText}>
            This permanently removes your login and all of your portfolio
            records. Type <strong>DELETE</strong> to confirm.
          </p>
          <div className={styles.confirmRow}>
            <input
              className={`filter-select ${styles.confirmInput}`}
              value={confirmText}
              onChange={e => setConfirmText(e.target.value)}
              placeholder="DELETE"
              aria-label="Type DELETE to confirm"
              autoFocus
            />
            <button
              className="btn-outline btn-sm btn-danger"
              onClick={handleDelete}
              disabled={!canDelete || busy}
            >
              {busy ? 'Deleting…' : 'Permanently delete'}
            </button>
            <button className="btn-outline btn-sm" onClick={cancel} disabled={busy}>
              Cancel
            </button>
          </div>
          {error && <StatusMessage ok={false}>{error}</StatusMessage>}
        </>
      )}
    </section>
  )
}
