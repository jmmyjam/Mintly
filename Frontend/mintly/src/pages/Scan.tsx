import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { filterCards, searchCards, getCardPrice, type Card, type CardPage } from '../api'
import CameraViewfinder from '../components/CameraViewfinder'
import CardImage from '../components/CardImage'
import PriceQtyForm from '../components/PriceQtyForm'
import StatusMessage from '../components/StatusMessage'
import { useAddCard } from '../hooks'
import { readCard, normNumber, warmUpOcr, type CardReading } from '../ocr'
import { money } from '../format'
import styles from './Scan.module.css'

export default function Scan() {
  const [captured, setCaptured] = useState<string | null>(null) // thumbnail data URL
  const [reading, setReading] = useState(false) // OCR in progress
  const [nameField, setNameField] = useState('')
  const [numberField, setNumberField] = useState('')
  const [results, setResults] = useState<Card[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  // ?debug (any value) surfaces exactly what OCR was given and returned
  const [searchParams] = useSearchParams()
  const debug = searchParams.has('debug')
  const [debugInfo, setDebugInfo] = useState<CardReading['debug'] | null>(null)
  const [ocrError, setOcrError] = useState<string | null>(null)

  // Shared add-to-portfolio flow, same as Search/CardDetail
  const { add, busy: addBusy, status: addStatus } = useAddCard()
  const [adding, setAdding] = useState<string | null>(null)
  const [purchasePrice, setPurchasePrice] = useState('')
  const [quantity, setQuantity] = useState('1')

  // Start downloading the OCR model while the user lines up the card
  useEffect(() => {
    warmUpOcr()
  }, [])

  // Name-first lookup: the number narrows it when legible, but a readable name
  // alone must still surface a best guess (per the plan). First non-empty wins.
  async function runLookup(name: string, rawNumber: string) {
    const cleanName = name.trim()
    const num = normNumber(rawNumber)
    if (!cleanName && !num) {
      setNotice('Type at least the card name, then tap Find card.')
      return
    }
    setSearching(true)
    setResults(null)
    setNotice(null)

    // Each step is independent: a single failing query (e.g. the backend 500s on
    // an odd name+number combo) falls through to the next instead of aborting the
    // whole lookup and losing the name-only fallback that would have worked.
    const step = async (fn: () => Promise<CardPage>): Promise<Card[]> => {
      try {
        return (await fn()).data
      } catch (err) {
        console.error('[scan] lookup step failed', err)
        return []
      }
    }

    let data: Card[] = []
    if (cleanName && num) data = await step(() => filterCards({ name: cleanName, number: num }))
    if (data.length === 0 && cleanName) data = await step(() => filterCards({ name: cleanName }))
    if (data.length === 0) {
      const q = `${cleanName} ${rawNumber}`.trim()
      if (q) data = await step(() => searchCards(q))
    }

    setResults(data)
    if (data.length === 0) setNotice('No match found. Edit the name or number and try again.')
    setSearching(false)
  }

  async function handleCapture(card: HTMLCanvasElement) {
    setCaptured(card.toDataURL('image/jpeg', 0.8))
    setResults(null)
    setNotice(null)
    setDebugInfo(null)
    setOcrError(null)
    setReading(true)
    try {
      const r = await readCard(card, { debug })
      setNameField(r.name)
      setNumberField(r.rawNumber)
      if (r.debug) setDebugInfo(r.debug)
      setReading(false)
      if (r.name || r.rawNumber) {
        await runLookup(r.name, r.rawNumber)
      } else {
        setNotice("Couldn't read the card — type the name below and tap Find card.")
      }
    } catch (err) {
      setReading(false)
      setOcrError(err instanceof Error ? err.message : String(err))
      setNotice("Couldn't read the card — type the name below and tap Find card.")
    }
  }

  function reset() {
    setCaptured(null)
    setResults(null)
    setNameField('')
    setNumberField('')
    setNotice(null)
    setDebugInfo(null)
    setOcrError(null)
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
                // Priceless cards can't auto-price on add — seed the eBay estimate
                if (price == null && card.estimate) setPurchasePrice(card.estimate.value.toFixed(2))
              }}
            >
              + Portfolio
            </button>
          ))}
      </div>
    )
  }

  return (
    <div className="page">
      <h1>Scan a card</h1>
      {debug && (
        <p className={styles.debugBanner}>
          🔍 Debug mode on — the OCR crops &amp; raw text appear at the bottom after each scan.
        </p>
      )}

      {!captured ? (
        <>
          <p className={styles.intro}>
            Point your camera at a Pokémon card and line it up inside the frame. Mintly reads the
            card name and number right on your device — no photo is uploaded — then finds the match
            so you can add it to your portfolio.
          </p>
          <p className={styles.tips}>
            For the best read: fill the frame with the card, hold it flat and steady so it&apos;s in
            focus, use good light, and tilt slightly to keep glare off the name.
          </p>
          <CameraViewfinder onCapture={handleCapture} busy={reading} />
        </>
      ) : (
        <div className={styles.review}>
          <div className={styles.capturePane}>
            <img src={captured} alt="Captured card" className={styles.thumb} />
            <button className="btn-outline btn-sm" onClick={reset}>
              Scan another
            </button>
          </div>
          <div className={styles.readPane}>
            <p className={styles.readIntro}>Check what we read, fix anything, then find the card.</p>
            <label className="edit-field">
              <span className="stat-label">Card name</span>
              <input
                className="mini-input"
                value={nameField}
                onChange={(e) => setNameField(e.target.value)}
                placeholder="e.g. Charizard"
              />
            </label>
            <label className="edit-field">
              <span className="stat-label">Number (bottom of card)</span>
              <input
                className="mini-input"
                value={numberField}
                onChange={(e) => setNumberField(e.target.value)}
                placeholder="e.g. 4/102"
              />
            </label>
            <button
              className="btn-primary"
              onClick={() => runLookup(nameField, numberField)}
              disabled={reading || searching}
            >
              {reading ? 'Reading…' : searching ? 'Finding…' : 'Find card'}
            </button>
          </div>
        </div>
      )}

      {captured && (
        <div className={styles.results}>
          {reading && <p className={styles.status}>Reading the card…</p>}
          {searching && <p className={styles.status}>Finding matches…</p>}
          {notice && <p className="prices-note">{notice}</p>}
          {results && results.length === 0 && !!nameField.trim() && (
            <p className={styles.manual}>
              <Link to={`/search?q=${encodeURIComponent(nameField.trim())}`}>
                Search the catalog manually →
              </Link>
            </p>
          )}

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
        </div>
      )}

      {debug && (
        <div className={styles.debug}>
          <h3 className={styles.debugHeading}>Debug · what OCR saw</h3>
          {ocrError && <p className="error">OCR error: {ocrError}</p>}
          {reading && <p className={styles.status}>Running OCR…</p>}
          {debugInfo ? (
            <div className={styles.debugGrid}>
              <figure className={styles.debugFig}>
                <img src={debugInfo.nameCropUrl} alt="name crop sent to OCR" />
                <figcaption>name crop → “{debugInfo.rawName || '(empty)'}”</figcaption>
              </figure>
              <figure className={styles.debugFig}>
                <img src={debugInfo.numberCropUrl} alt="number crop sent to OCR" />
                <figcaption>number crop → “{debugInfo.rawNumber || '(empty)'}”</figcaption>
              </figure>
            </div>
          ) : (
            !reading &&
            !ocrError && (
              <p className={styles.status}>Scan a card and the two crops OCR receives will show here.</p>
            )
          )}
        </div>
      )}
    </div>
  )
}
