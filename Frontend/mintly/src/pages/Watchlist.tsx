import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  CONNECTION_ERROR, errorMessage, getToken, getWatchlist, removeFromWatchlist,
  SessionExpiredError, updateWatchlistItem, type WatchlistItem,
} from '../api'
import CardImage from '../components/CardImage'
import DayChange from '../components/DayChange'
import PageMessage from '../components/PageMessage'
import StatusMessage from '../components/StatusMessage'
import { useSessionRedirect } from '../hooks'
import { money } from '../format'
import styles from './Watchlist.module.css'

export default function Watchlist() {
  if (!getToken()) {
    return (
      <PageMessage action={{ to: '/login', label: 'Log in' }}>
        <p>Log in to build a watchlist and get an email when a card hits your target price.</p>
      </PageMessage>
    )
  }
  return <WatchlistView />
}

function WatchlistView() {
  const [items, setItems] = useState<WatchlistItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const redirectToLogin = useSessionRedirect()

  function reload() {
    return getWatchlist()
      .then(list => {
        setItems(list)
        setLoading(false)
      })
      .catch(err => {
        if (err instanceof SessionExpiredError) {
          redirectToLogin()
          return
        }
        setError(
          err instanceof TypeError
            ? CONNECTION_ERROR
            : "We couldn't load your watchlist right now. Please try again in a moment.",
        )
        setLoading(false)
      })
  }

  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const header = (
    <header className={styles.header}>
      <h1 className={styles.title}>Watchlist</h1>
      <p className={styles.intro}>
        Track cards you don&apos;t own yet. Set a target price and we&apos;ll email you when
        it drops below (or rises above) it.
      </p>
    </header>
  )

  if (loading) return <PageMessage><p>Loading watchlist...</p></PageMessage>
  if (error) {
    return (
      <div className="page">
        {header}
        <p className="error">{error}</p>
      </div>
    )
  }
  if (items.length === 0) {
    return (
      <div className="page">
        {header}
        <p className={styles.empty}>
          Your watchlist is empty. Find a card in <Link to="/search">Search</Link>, open it, and
          choose <b>Watch this card</b> to start tracking its price.
        </p>
      </div>
    )
  }

  return (
    <div className="page">
      {header}
      <ul className={styles.grid}>
        {items.map(item => (
          <WatchlistRow key={item.id} item={item} onChanged={reload} onRedirect={redirectToLogin} />
        ))}
      </ul>
    </div>
  )
}

type RowMode = 'view' | 'edit' | 'confirmRemove'

function WatchlistRow({ item, onChanged, onRedirect }: {
  item: WatchlistItem
  onChanged: () => void
  onRedirect: () => void
}) {
  const [mode, setMode] = useState<RowMode>('view')
  const [target, setTarget] = useState(item.target_price != null ? String(item.target_price) : '')
  const [direction, setDirection] = useState<'below' | 'above'>(item.direction)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  function startEdit() {
    setTarget(item.target_price != null ? String(item.target_price) : '')
    setDirection(item.direction)
    setError('')
    setMode('edit')
  }

  async function run(action: () => Promise<void>) {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await action()
      // reload() refreshes the list but keeps this row mounted (stable key), so
      // reset mode/busy here rather than relying on a remount.
      onChanged()
      setMode('view')
      setBusy(false)
    } catch (err: unknown) {
      if (err instanceof SessionExpiredError) {
        onRedirect()
        return
      }
      setError(errorMessage(err, "We couldn't save that change. Please try again."))
      setBusy(false)
    }
  }

  function save() {
    const raw = target.trim()
    const parsed = raw === '' ? null : parseFloat(raw)
    const targetPrice = parsed != null && !Number.isNaN(parsed) && parsed >= 0 ? parsed : null
    run(() => updateWatchlistItem(item.id, targetPrice, direction))
  }

  const verb = item.direction === 'above' ? 'above' : 'below'

  return (
    <li className={styles.tile}>
      <Link to={`/card/${item.card_id}`} className={styles.tileArt} aria-label={item.card_name}>
        <CardImage src={item.image_url ?? undefined} alt={item.card_name} size="tile" />
      </Link>
      <div className={styles.tileBody}>
        <Link to={`/card/${item.card_id}`} className={styles.tileName}>{item.card_name}</Link>
        <div className={styles.tilePrice}>
          <span className={styles.tilePriceValue}>
            {item.current_price != null ? money(item.current_price) : '—'}
          </span>
          {item.price_change && <DayChange change={item.price_change} today />}
        </div>

        {mode === 'edit' ? (
          <div className={styles.edit}>
            <select
              className="filter-select"
              value={direction}
              onChange={e => setDirection(e.target.value as 'below' | 'above')}
              aria-label="Alert direction"
            >
              <option value="below">Alert below</option>
              <option value="above">Alert above</option>
            </select>
            <span className={styles.editPrice}>
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
                className={styles.editInput}
              />
            </span>
            <button type="button" className="btn-primary btn-sm" onClick={save} disabled={busy}>
              {busy ? 'Saving…' : 'Save'}
            </button>
            <button type="button" className="btn-outline btn-sm" onClick={() => setMode('view')} disabled={busy}>
              Cancel
            </button>
          </div>
        ) : mode === 'confirmRemove' ? (
          <div className={styles.alert}>
            <span className={styles.alertNone}>Remove from watchlist?</span>
            <div className={styles.alertActions}>
              <button type="button" className={`${styles.linkBtn} ${styles.danger}`}
                      onClick={() => run(() => removeFromWatchlist(item.id))} disabled={busy}>
                Remove
              </button>
              <button type="button" className={styles.linkBtn}
                      onClick={() => setMode('view')} disabled={busy}>
                Keep
              </button>
            </div>
          </div>
        ) : (
          <div className={styles.alert}>
            {item.target_price != null ? (
              <span className={`${styles.alertChip}${item.triggered ? ` ${styles.triggered}` : ''}`}>
                {item.triggered && <span aria-hidden="true">●</span>}
                {item.triggered ? 'Target hit: ' : 'Alert '}
                {verb} {money(item.target_price)}
              </span>
            ) : (
              <span className={styles.alertNone}>No price alert</span>
            )}
            <div className={styles.alertActions}>
              <button type="button" className={styles.linkBtn} onClick={startEdit}>
                {item.target_price != null ? 'Edit' : 'Add alert'}
              </button>
              <button type="button" className={styles.linkBtn} onClick={() => setMode('confirmRemove')}>
                Remove
              </button>
            </div>
          </div>
        )}
        {error && <StatusMessage ok={false}>{error}</StatusMessage>}
      </div>
    </li>
  )
}
