import { useEffect, useRef, useState } from 'react'
import { addCardBatch, SessionExpiredError, type PortfolioCard, type BatchAddItem } from '../api'
import { toPortfolioCsv, parsePortfolioCsv, type ParsedPortfolioCsv } from '../portfolioCsv'
import { invalidateOwned } from '../owned'
import { useSessionRedirect } from '../hooks'
import StatusMessage from './StatusMessage'
import styles from './PortfolioCsv.module.css'

// Data portability for the Portfolio page: export the whole portfolio to a CSV
// (one row per lot, so it round-trips) and import a CSV to bulk-seed or restore a
// collection through the existing batch adder. Import always adds new lots (it
// never replaces), so the preview warns before committing. add-batch caps at 100
// items per request, so a larger import is chunked.
const CHUNK = 100

type ImportResult = { added: number; failed: { card_id: string; reason: string }[] }

const plural = (n: number, one: string) => `${n} ${n === 1 ? one : one + 's'}`

export default function PortfolioCsv({ cards, onImported, portfolioId }: { cards: PortfolioCard[]; onImported: () => void; portfolioId?: number | null }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const [parsed, setParsed] = useState<ParsedPortfolioCsv | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const redirectToLogin = useSessionRedirect()

  // Close the dropdown on an outside click or Escape (only while it's open).
  useEffect(() => {
    if (!menuOpen) return
    function onDown(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  function reset() {
    setParsed(null)
    setResult(null)
    setError('')
  }

  function onExportClick() {
    setMenuOpen(false)
    handleExport()
  }

  function onImportClick() {
    setMenuOpen(false)
    fileRef.current?.click()
  }

  function handleExport() {
    const blob = new Blob([toPortfolioCsv(cards)], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `mintly-portfolio-${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // let the same file be re-selected later
    if (!file) return
    reset()
    let text: string
    try {
      text = await file.text()
    } catch {
      setError("We couldn't read that file. Please try again.")
      return
    }
    const p = parsePortfolioCsv(text)
    if (p.items.length === 0) {
      setError(
        p.skipped > 0
          ? 'No rows had a card id, so there was nothing to import.'
          : "That file didn't contain any card rows. It needs a card_id column.",
      )
      return
    }
    setParsed(p)
  }

  async function handleImport() {
    if (!parsed) return
    setBusy(true)
    setError('')
    try {
      let added = 0
      const failed: ImportResult['failed'] = []
      for (let i = 0; i < parsed.items.length; i += CHUNK) {
        const res = await addCardBatch(parsed.items.slice(i, i + CHUNK) as BatchAddItem[], portfolioId)
        added += res.added
        failed.push(...res.failed)
      }
      setParsed(null)
      setResult({ added, failed })
      invalidateOwned()
      onImported()
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        redirectToLogin()
        return
      }
      setParsed(null)
      setError("We couldn't finish importing. Some cards may have been added, so reload to check before trying again.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.root}>
      <div className={styles.bar}>
        <div className={styles.menuWrap} ref={menuRef}>
          <button
            type="button"
            className={styles.trigger}
            onClick={() => setMenuOpen(o => !o)}
            disabled={busy}
            aria-haspopup="true"
            aria-expanded={menuOpen}
            aria-label="Import or export CSV"
            title="Import or export CSV"
          >
            ⋮
          </button>
          {menuOpen && (
            <div className={styles.menu} role="menu">
              <button
                type="button"
                className={styles.menuItem}
                role="menuitem"
                onClick={onExportClick}
                disabled={cards.length === 0}
              >
                Export CSV
              </button>
              <button type="button" className={styles.menuItem} role="menuitem" onClick={onImportClick}>
                Import CSV
              </button>
            </div>
          )}
        </div>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          onChange={handleFile}
          style={{ display: 'none' }}
          aria-hidden="true"
          tabIndex={-1}
        />
      </div>

      {(parsed || result || error) && (
        <div className={styles.panel}>
          {error && <StatusMessage ok={false}>{error}</StatusMessage>}

          {parsed && (
            <>
              <p className={styles.summary}>
                {plural(parsed.items.length, 'lot')} ready to import
                {parsed.skipped > 0 && ` (${plural(parsed.skipped, 'row')} skipped: no card id)`}
              </p>
              <p className={styles.note}>This adds them as new lots. It does not replace your current portfolio.</p>
              <div className={styles.actions}>
                <button className="btn-primary" onClick={handleImport} disabled={busy}>
                  {busy ? 'Importing...' : `Import ${plural(parsed.items.length, 'lot')}`}
                </button>
                <button className="btn-outline" onClick={reset} disabled={busy}>Cancel</button>
              </div>
            </>
          )}

          {result && (
            <>
              <StatusMessage ok={result.failed.length === 0}>
                {result.added > 0 ? `Added ${plural(result.added, 'card')} to your portfolio.` : 'No cards were added.'}
                {result.failed.length > 0 && ` ${plural(result.failed.length, 'row')} couldn't be added.`}
              </StatusMessage>
              {result.failed.length > 0 && (
                <ul className={styles.failList}>
                  {result.failed.slice(0, 10).map((f, i) => (
                    <li key={i}><span className="num">{f.card_id}</span>: {f.reason}</li>
                  ))}
                  {result.failed.length > 10 && <li>and {result.failed.length - 10} more</li>}
                </ul>
              )}
              <div className={styles.actions}>
                <button className="btn-outline" onClick={reset}>Done</button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
