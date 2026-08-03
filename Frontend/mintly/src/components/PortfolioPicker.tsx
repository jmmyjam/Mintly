import { useState } from 'react'
import { createPortfolio, SessionExpiredError } from '../api'
import { usePortfolios } from '../portfolios'
import { useSessionRedirect } from '../hooks'
import styles from './PortfolioPicker.module.css'

// A compact "which portfolio does this add go to" chooser. Used by the single-add
// forms (Search / CardDetail / single scan) and the Scan batch queue header. The
// selection defaults to the active portfolio; `allowCreate` adds a "New
// portfolio…" option that creates one inline (used by batch add).
//
// Renders nothing when there's only one portfolio and creating is disabled —
// there's no choice to make, so the common single-portfolio case stays clean.

const NEW = '__new__'

interface Props {
  value: number | null
  onChange: (id: number) => void
  allowCreate?: boolean
  label?: string
  ariaLabel?: string
  className?: string
}

export default function PortfolioPicker({
  value,
  onChange,
  allowCreate = false,
  label,
  ariaLabel = 'Add to portfolio',
  className,
}: Props) {
  const { portfolios, activeId, refresh } = usePortfolios()
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const redirectToLogin = useSessionRedirect()

  const selected = value ?? activeId

  if (portfolios.length <= 1 && !allowCreate) return null

  function onSelect(e: React.ChangeEvent<HTMLSelectElement>) {
    if (e.target.value === NEW) {
      setCreating(true)
      setNewName('')
      setError('')
      return
    }
    onChange(Number(e.target.value))
  }

  async function submitCreate() {
    const name = newName.trim()
    if (!name || busy) return
    setBusy(true)
    setError('')
    try {
      const p = await createPortfolio(name)
      await refresh()
      onChange(p.id)
      setCreating(false)
      setNewName('')
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        redirectToLogin()
        return
      }
      setError(err instanceof Error ? err.message : "We couldn't create that portfolio.")
    } finally {
      setBusy(false)
    }
  }

  if (creating) {
    return (
      <span className={`${styles.createRow} ${className ?? ''}`}>
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
        <button type="button" className="btn-outline btn-sm" disabled={busy} onClick={() => { setCreating(false); setError('') }}>
          Cancel
        </button>
        {error && <span className={styles.error}>{error}</span>}
      </span>
    )
  }

  return (
    <span className={`${styles.root} ${className ?? ''}`}>
      {label && <span className={styles.label}>{label}</span>}
      <select
        className={`filter-select ${styles.select}`}
        value={selected ?? ''}
        onChange={onSelect}
        aria-label={ariaLabel}
      >
        {portfolios.map(p => (
          <option key={p.id} value={p.id}>{p.name}</option>
        ))}
        {allowCreate && <option value={NEW}>＋ New portfolio…</option>}
      </select>
    </span>
  )
}
