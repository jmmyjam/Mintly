import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  scanCard,
  addCardBatch,
  getCardPrice,
  getToken,
  errorMessage,
  SessionExpiredError,
  type Card,
} from '../api'
import CameraViewfinder from '../components/CameraViewfinder'
import CardImage from '../components/CardImage'
import CandidatePickerModal from '../components/CandidatePickerModal'
import PriceQtyForm from '../components/PriceQtyForm'
import SignedOutHero from '../components/SignedOutHero'
import StatusMessage from '../components/StatusMessage'
import { useAddCard, useSessionRedirect } from '../hooks'
import { money } from '../format'
import styles from './Scan.module.css'

// CLIP cosine similarity below this marks a best-guess as shaky ("Check this")
// in batch mode. Good matches observed roughly 0.8-0.95; tune against real
// captures. A card scanned before the embedding backfill has no score and is
// never flagged.
const SCAN_CONFIDENCE_FLOOR = 0.85

// One scanned card waiting in the batch queue: the photo, the ranked candidates
// the scan returned, which one is currently chosen, and the price/qty to add it at.
interface QueueItem {
  key: string
  thumbnail: string
  candidates: Card[]
  selectedIndex: number
  price: string
  quantity: string
}

// The market price (or eBay estimate) to pre-fill a queued card's price with —
// same order the single-add form uses, so the value shown is the value added.
function defaultPriceFor(card: Card): string {
  const price = getCardPrice(card)
  if (price != null) return price.toFixed(2)
  if (card.estimate) return card.estimate.value.toFixed(2)
  return ''
}

export default function Scan() {
  const navigate = useNavigate()
  const redirectToLogin = useSessionRedirect()
  const [batchMode, setBatchMode] = useState(false)
  const [captured, setCaptured] = useState<string | null>(null) // thumbnail data URL
  const [matching, setMatching] = useState(false) // upload + match in flight
  const [results, setResults] = useState<Card[] | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [manualQuery, setManualQuery] = useState('')

  // Shared add-to-portfolio flow (single mode), same as Search/CardDetail
  const { add, busy: addBusy, status: addStatus } = useAddCard()
  const [adding, setAdding] = useState<string | null>(null)
  const [purchasePrice, setPurchasePrice] = useState('')
  const [quantity, setQuantity] = useState('1')

  // Batch mode
  const [queue, setQueue] = useState<QueueItem[]>([])
  const [overrideKey, setOverrideKey] = useState<string | null>(null)
  const [committing, setCommitting] = useState(false)
  const [batchStatus, setBatchStatus] = useState<{ msg: string; ok: boolean } | null>(null)
  const [lastAdded, setLastAdded] = useState<string | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)

  function handleCapture(canvas: HTMLCanvasElement) {
    const thumb = canvas.toDataURL('image/jpeg', 0.85)

    if (batchMode) {
      setNotice(null)
      setMatching(true)
      canvas.toBlob(
        (blob) => {
          if (!blob) {
            setMatching(false)
            setNotice("Couldn't read the capture. Try again.")
            return
          }
          scanCard(blob)
            .then((page) => {
              if (page.data.length === 0) {
                setNotice('No match for that one. Line the card up and scan it again.')
                return
              }
              const best = page.data[0]
              setQueue((q) => [
                ...q,
                {
                  key: `${Date.now()}-${q.length}`,
                  thumbnail: thumb,
                  candidates: page.data,
                  selectedIndex: 0,
                  price: defaultPriceFor(best),
                  quantity: '1',
                },
              ])
              setLastAdded(best.name)
              setTimeout(() => setLastAdded(null), 2500)
            })
            .catch((err) => {
              if (err instanceof SessionExpiredError) {
                redirectToLogin()
                return
              }
              setNotice('Something went wrong scanning. Please try again.')
            })
            .finally(() => setMatching(false))
        },
        'image/jpeg',
        0.85,
      )
      return
    }

    // Single mode (unchanged)
    setCaptured(thumb)
    setResults(null)
    setNotice(null)
    setMatching(true)
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          setMatching(false)
          setNotice("Couldn't read the capture. Try again.")
          return
        }
        scanCard(blob)
          .then((page) => {
            setResults(page.data)
            if (page.data.length === 0) {
              setNotice('No match found. Try scanning again, or search by name below.')
            }
          })
          .catch((err) => {
            if (err instanceof SessionExpiredError) {
              redirectToLogin()
              return
            }
            setResults([])
            setNotice('Something went wrong scanning. Please try again.')
          })
          .finally(() => setMatching(false))
      },
      'image/jpeg',
      0.85,
    )
  }

  function reset() {
    setCaptured(null)
    setResults(null)
    setNotice(null)
    setAdding(null)
    setPurchasePrice('')
    setQuantity('1')
  }

  function handleAdd(card: Card) {
    add(card.id, purchasePrice, quantity, () => {
      setAdding(null)
      setPurchasePrice('')
      setQuantity('1')
    })
  }

  function manualSearch(e: React.FormEvent) {
    e.preventDefault()
    const q = manualQuery.trim()
    if (q) navigate(`/search?q=${encodeURIComponent(q)}`)
  }

  // ----- Batch helpers -------------------------------------------------------

  function doSwitch(toBatch: boolean) {
    setBatchMode(toBatch)
    setConfirmClear(false)
    reset()
    setQueue([])
    setBatchStatus(null)
    setOverrideKey(null)
    setLastAdded(null)
  }

  function switchMode(toBatch: boolean) {
    if (toBatch === batchMode) return
    // Leaving batch with a pending queue: two-step inline confirm (no native confirm())
    if (!toBatch && queue.length > 0) {
      setConfirmClear(true)
      return
    }
    doSwitch(toBatch)
  }

  function updateItem(key: string, patch: Partial<QueueItem>) {
    setQueue((q) => q.map((it) => (it.key === key ? { ...it, ...patch } : it)))
  }

  function removeItem(key: string) {
    setQueue((q) => q.filter((it) => it.key !== key))
    if (overrideKey === key) setOverrideKey(null)
  }

  // Override modal picked a different candidate: switch to it and re-seed the
  // price from the newly chosen card (the old price was for the wrong card).
  function chooseCandidate(index: number) {
    if (!overrideKey) return
    setQueue((q) =>
      q.map((it) =>
        it.key === overrideKey
          ? { ...it, selectedIndex: index, price: defaultPriceFor(it.candidates[index]) }
          : it,
      ),
    )
    setOverrideKey(null)
  }

  async function commitBatch() {
    if (!queue.length || committing) return
    setCommitting(true)
    setBatchStatus(null)
    try {
      const items = queue.map((it) => {
        const card = it.candidates[it.selectedIndex]
        const price = parseFloat(it.price)
        return {
          card_id: card.id,
          purchase_price: Number.isNaN(price) ? null : price,
          quantity: parseInt(it.quantity, 10) || 1,
        }
      })
      const result = await addCardBatch(items)
      if (result.failed.length === 0) {
        setBatchStatus({ msg: result.message, ok: true })
        setQueue([])
      } else {
        // Keep the cards that couldn't be added so they can be fixed and retried
        const failedIds = new Set(result.failed.map((f) => f.card_id))
        setQueue((q) => q.filter((it) => failedIds.has(it.candidates[it.selectedIndex].id)))
        setBatchStatus({
          msg: `Added ${result.added}. ${result.failed.length} couldn't be added and are still listed below.`,
          ok: result.added > 0,
        })
      }
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        redirectToLogin()
        return
      }
      setBatchStatus({ msg: errorMessage(err, "We couldn't add those cards. Please try again."), ok: false })
    } finally {
      setCommitting(false)
    }
  }

  // ----- Single-mode result tile (unchanged) ---------------------------------

  function renderTile(card: Card, best = false) {
    const price = getCardPrice(card)
    const isAdding = adding === card.id
    const status = addStatus?.id === card.id ? addStatus : null

    return (
      <div key={card.id} className={best ? `${styles.tile} ${styles.tileBest}` : styles.tile}>
        {best && <span className={styles.badge}>Best match</span>}
        <Link to={`/card/${card.id}`} className="card-link">
          <CardImage src={card.images.small} alt={card.name} />
          <div className={styles.info}>
            <p className="card-name">{card.name}</p>
            <p className="card-set">
              {card.set.name}
              {card.number ? ` · ${card.number}` : ''}
            </p>
            {price != null ? (
              <p className={styles.price}>{money(price)}</p>
            ) : card.estimate ? (
              <p className={styles.price}>
                {money(card.estimate.value)} <span className={styles.est}>eBay est.</span>
              </p>
            ) : null}
          </div>
        </Link>

        {status && <StatusMessage ok={status.ok}>{status.msg}</StatusMessage>}

        {!status &&
          (isAdding ? (
            <PriceQtyForm
              price={purchasePrice}
              quantity={quantity}
              onPriceChange={setPurchasePrice}
              onQuantityChange={setQuantity}
              onSubmit={() => handleAdd(card)}
              submitLabel="Add"
              busyLabel="Adding..."
              busy={addBusy}
              smallButtons
              onCancel={() => {
                setAdding(null)
                setPurchasePrice('')
                setQuantity('1')
              }}
            />
          ) : (
            <button
              className="btn-outline btn-sm"
              onClick={() => {
                setAdding(card.id)
                if (price == null && card.estimate) setPurchasePrice(card.estimate.value.toFixed(2))
              }}
            >
              + Portfolio
            </button>
          ))}
      </div>
    )
  }

  // ----- Batch-mode queue row ------------------------------------------------

  function renderQueueRow(item: QueueItem) {
    const card = item.candidates[item.selectedIndex]
    const shaky = card.matchScore != null && card.matchScore < SCAN_CONFIDENCE_FLOOR

    return (
      <li key={item.key} className={styles.queueRow}>
        <img src={item.thumbnail} alt="Scanned card" className={styles.queueThumb} />
        <div className={styles.queueArt}>
          <CardImage src={card.images.small} alt={card.name} />
        </div>
        <div className={styles.queueInfo}>
          <div className={styles.queueNameRow}>
            <Link to={`/card/${card.id}`} className={styles.queueName}>
              {card.name}
            </Link>
            {shaky && <span className={styles.checkBadge}>Check this</span>}
          </div>
          <p className={styles.queueSet}>
            {card.set.name}
            {card.number ? ` · ${card.number}` : ''}
          </p>
          <div className={styles.queueControls}>
            <input
              type="number"
              className="mini-input"
              placeholder="Price paid($)"
              aria-label="Price paid"
              min="0"
              step="0.01"
              value={item.price}
              onChange={(e) => updateItem(item.key, { price: e.target.value })}
            />
            <input
              type="number"
              className="mini-input mini-qty"
              placeholder="Qty"
              aria-label="Quantity"
              min="1"
              value={item.quantity}
              onChange={(e) => updateItem(item.key, { quantity: e.target.value })}
            />
            <button className="btn-outline btn-sm" onClick={() => setOverrideKey(item.key)}>
              Change
            </button>
            <button
              type="button"
              className={styles.removeBtn}
              aria-label={`Remove ${card.name}`}
              onClick={() => removeItem(item.key)}
            >
              ✕
            </button>
          </div>
        </div>
      </li>
    )
  }

  if (!getToken()) {
    return <SignedOutHero variant="scan" />
  }

  const overrideItem = queue.find((it) => it.key === overrideKey) || null

  return (
    <div className="page">
      <h1>Scan a card</h1>

      <div className={styles.modeToggle} role="group" aria-label="Scan mode">
        <button
          className={!batchMode ? `${styles.modeBtn} ${styles.modeActive}` : styles.modeBtn}
          aria-pressed={!batchMode}
          onClick={() => switchMode(false)}
        >
          Single
        </button>
        <button
          className={batchMode ? `${styles.modeBtn} ${styles.modeActive}` : styles.modeBtn}
          aria-pressed={batchMode}
          onClick={() => switchMode(true)}
        >
          Batch add
        </button>
      </div>

      {confirmClear && (
        <div className={styles.confirmClear}>
          <span>
            Switch to single scan? Your {queue.length} scanned{' '}
            {queue.length === 1 ? 'card' : 'cards'} will be discarded.
          </span>
          <div className={styles.confirmButtons}>
            <button className="btn-outline btn-sm" onClick={() => doSwitch(false)}>
              Discard and switch
            </button>
            <button className="btn-primary btn-sm" onClick={() => setConfirmClear(false)}>
              Keep scanning
            </button>
          </div>
        </div>
      )}

      {batchMode ? (
        // ----- Batch mode -----
        <>
          <p className={styles.intro}>
            Scan card after card. Mintly takes its best guess for each and lists them below, then you
            add the whole batch to your portfolio at once. Tap Change on any card to pick a different
            match or rescan it.
          </p>
          <CameraViewfinder onCapture={handleCapture} busy={matching} />

          <div className={styles.batchStatusLine}>
            {matching && <span className={styles.status}>Finding your card…</span>}
            {!matching && lastAdded && <span className={styles.added}>Added {lastAdded} to the batch</span>}
            {notice && <span className="prices-note">{notice}</span>}
          </div>

          <div className={styles.batchPanel}>
            <div className={styles.batchHeader}>
              <h2 className={styles.batchTitle}>
                Batch{queue.length > 0 ? ` (${queue.length})` : ''}
              </h2>
              <button
                className="btn-primary"
                disabled={queue.length === 0 || committing}
                onClick={commitBatch}
              >
                {committing
                  ? 'Adding…'
                  : `Add all${queue.length > 0 ? ` ${queue.length}` : ''} to portfolio`}
              </button>
            </div>

            {batchStatus && <StatusMessage ok={batchStatus.ok}>{batchStatus.msg}</StatusMessage>}

            {queue.length === 0 ? (
              <p className="prices-note">Scanned cards collect here. Nothing is added until you tap Add all.</p>
            ) : (
              <ul className={styles.queue}>{queue.map(renderQueueRow)}</ul>
            )}
          </div>
        </>
      ) : (
        // ----- Single mode (unchanged) -----
        <>
          {!captured ? (
            <>
              <p className={styles.intro}>
                Point your camera at a Pokémon card and line it up inside the frame. Mintly matches the
                photo against its card database to find it, then you can add it to your portfolio.
              </p>
              <p className={styles.tips}>
                For the best match: fill the frame with the card, hold steady so it&apos;s in focus, and
                use good, even light.
              </p>
              <CameraViewfinder onCapture={handleCapture} busy={matching} />
            </>
          ) : (
            <div className={styles.review}>
              <img src={captured} alt="Captured card" className={styles.thumb} />
              <button className="btn-outline btn-sm" onClick={reset}>
                Scan another
              </button>
            </div>
          )}

          {captured && (
            <div className={styles.results}>
              {matching && <p className={styles.status}>Finding your card…</p>}
              {notice && <p className="prices-note">{notice}</p>}

              {results && results.length > 0 && (
                <>
                  <h2 className={styles.bestHeading}>We think this is…</h2>
                  <div className={styles.grid}>{renderTile(results[0], true)}</div>
                  {results.length > 1 && (
                    <>
                      <h3 className={styles.otherHeading}>Other matches</h3>
                      <div className={styles.grid}>{results.slice(1).map((c) => renderTile(c))}</div>
                    </>
                  )}
                </>
              )}

              {!matching && (
                <form className={styles.manual} onSubmit={manualSearch}>
                  <input
                    className="mini-input"
                    value={manualQuery}
                    onChange={(e) => setManualQuery(e.target.value)}
                    placeholder="Not it? Search by name"
                    aria-label="Search by card name"
                  />
                  <button type="submit" className="btn-outline btn-sm">
                    Search
                  </button>
                </form>
              )}
            </div>
          )}
        </>
      )}

      {overrideItem && (
        <CandidatePickerModal
          candidates={overrideItem.candidates}
          selectedIndex={overrideItem.selectedIndex}
          onSelect={chooseCandidate}
          onRescan={() => removeItem(overrideItem.key)}
          onClose={() => setOverrideKey(null)}
        />
      )}
    </div>
  )
}
