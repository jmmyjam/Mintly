import { useEffect, useRef, useState } from 'react'
import { createPortfolio, renamePortfolio, deletePortfolio, SessionExpiredError } from '../api'
import { usePortfolios } from '../portfolios'
import { useSessionRedirect } from '../hooks'
import styles from './PortfolioSelector.module.css'

// The Portfolio page's header control: shows the active portfolio's name and
// opens a popover to switch, create, rename, and delete. The popover follows the
// PortfolioCsv kebab pattern (outside-click / Escape close). Deleting a portfolio
// removes its cards, so a non-empty one is gated behind a two-step confirm that
// names the count; the user's last remaining portfolio can't be deleted.

export default function PortfolioSelector() {
  const { portfolios, active, activeId, setActive, refresh } = usePortfolios()
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [renamingId, setRenamingId] = useState<number | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)
  const redirectToLogin = useSessionRedirect()

  // Close on outside click / Escape while open, and reset any inline sub-forms.
  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  function resetForms() {
    setCreating(false)
    setNewName('')
    setRenamingId(null)
    setRenameValue('')
    setConfirmDeleteId(null)
    setError('')
  }

  function toggle() {
    if (open) setOpen(false)
    else {
      resetForms()
      setOpen(true)
    }
  }

  function handleError(err: unknown, fallback: string) {
    if (err instanceof SessionExpiredError) {
      redirectToLogin()
      return
    }
    setError(err instanceof Error ? err.message : fallback)
  }

  function switchTo(id: number) {
    setActive(id)
    setOpen(false)
  }

  async function submitCreate() {
    const name = newName.trim()
    if (!name || busy) return
    setBusy(true)
    setError('')
    try {
      const p = await createPortfolio(name)
      await refresh()
      setActive(p.id)
      resetForms()
      setOpen(false)
    } catch (err) {
      handleError(err, "We couldn't create that portfolio.")
    } finally {
      setBusy(false)
    }
  }

  async function submitRename(id: number) {
    const name = renameValue.trim()
    if (!name || busy) return
    setBusy(true)
    setError('')
    try {
      await renamePortfolio(id, name)
      await refresh()
      setRenamingId(null)
      setRenameValue('')
    } catch (err) {
      handleError(err, "We couldn't rename that portfolio.")
    } finally {
      setBusy(false)
    }
  }

  async function submitDelete(id: number) {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await deletePortfolio(id)
      await refresh()
      setConfirmDeleteId(null)
    } catch (err) {
      handleError(err, "We couldn't delete that portfolio.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.root} ref={rootRef}>
      <button
        type="button"
        className={styles.trigger}
        onClick={toggle}
        aria-haspopup="true"
        aria-expanded={open}
      >
        <span className={styles.triggerName}>{active?.name ?? 'My Portfolio'}</span>
        <svg className={styles.chevron} viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div className={styles.menu}>
          <p className={styles.menuHead}>Your portfolios</p>
          <ul className={styles.list}>
            {portfolios.map(p => {
              const isActive = p.id === activeId
              if (renamingId === p.id) {
                return (
                  <li key={p.id} className={styles.row}>
                    <input
                      className={`mini-input ${styles.renameInput}`}
                      value={renameValue}
                      onChange={e => setRenameValue(e.target.value)}
                      maxLength={60}
                      autoFocus
                      aria-label="Portfolio name"
                      onKeyDown={e => {
                        if (e.key === 'Enter') { e.preventDefault(); submitRename(p.id) }
                        if (e.key === 'Escape') { setRenamingId(null); setError('') }
                      }}
                    />
                    <button type="button" className="btn-primary btn-sm" disabled={busy || !renameValue.trim()} onClick={() => submitRename(p.id)}>Save</button>
                    <button type="button" className="btn-outline btn-sm" disabled={busy} onClick={() => { setRenamingId(null); setError('') }}>Cancel</button>
                  </li>
                )
              }
              if (confirmDeleteId === p.id) {
                return (
                  <li key={p.id} className={`${styles.row} ${styles.confirmRow}`}>
                    <span className={styles.confirmText}>
                      Delete "{p.name}"{p.card_count > 0 ? ` and its ${p.card_count} ${p.card_count === 1 ? 'card' : 'cards'}` : ''}?
                    </span>
                    <button type="button" className={`btn-primary btn-sm ${styles.deleteYes}`} disabled={busy} onClick={() => submitDelete(p.id)}>Delete</button>
                    <button type="button" className="btn-outline btn-sm" disabled={busy} onClick={() => { setConfirmDeleteId(null); setError('') }}>Cancel</button>
                  </li>
                )
              }
              return (
                <li key={p.id} className={styles.row}>
                  <button
                    type="button"
                    className={`${styles.switch}${isActive ? ' ' + styles.switchActive : ''}`}
                    onClick={() => switchTo(p.id)}
                  >
                    <span className={styles.check} aria-hidden="true">{isActive ? '✓' : ''}</span>
                    <span className={styles.name}>{p.name}</span>
                    <span className={`${styles.count} num`}>{p.card_count}</span>
                  </button>
                  <span className={styles.rowActions}>
                    <button
                      type="button"
                      className={styles.iconBtn}
                      aria-label={`Rename ${p.name}`}
                      onClick={() => { setRenamingId(p.id); setRenameValue(p.name); setConfirmDeleteId(null); setError('') }}
                    >
                      Rename
                    </button>
                    {portfolios.length > 1 && (
                      <button
                        type="button"
                        className={`${styles.iconBtn} ${styles.deleteBtn}`}
                        aria-label={`Delete ${p.name}`}
                        onClick={() => { setConfirmDeleteId(p.id); setRenamingId(null); setError('') }}
                      >
                        Delete
                      </button>
                    )}
                  </span>
                </li>
              )
            })}
          </ul>

          {error && <p className={styles.error}>{error}</p>}

          {creating ? (
            <div className={styles.createRow}>
              <input
                className={`mini-input ${styles.createInput}`}
                value={newName}
                onChange={e => setNewName(e.target.value)}
                placeholder="New portfolio name"
                aria-label="New portfolio name"
                maxLength={60}
                autoFocus
                onKeyDown={e => {
                  if (e.key === 'Enter') { e.preventDefault(); submitCreate() }
                  if (e.key === 'Escape') { setCreating(false); setError('') }
                }}
              />
              <button type="button" className="btn-primary btn-sm" disabled={busy || !newName.trim()} onClick={submitCreate}>
                {busy ? 'Creating…' : 'Create'}
              </button>
              <button type="button" className="btn-outline btn-sm" disabled={busy} onClick={() => { setCreating(false); setError('') }}>Cancel</button>
            </div>
          ) : (
            <button type="button" className={styles.createBtn} onClick={() => { setCreating(true); setNewName(''); setError('') }}>
              ＋ New portfolio
            </button>
          )}
        </div>
      )}
    </div>
  )
}
