import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { scanCard, getCardPrice, getToken, SessionExpiredError, type Card } from '../api'
import CameraViewfinder from '../components/CameraViewfinder'
import CardImage from '../components/CardImage'
import PageMessage from '../components/PageMessage'
import PriceQtyForm from '../components/PriceQtyForm'
import StatusMessage from '../components/StatusMessage'
import { useAddCard, useSessionRedirect } from '../hooks'
import { money } from '../format'
import styles from './Scan.module.css'

export default function Scan() {
  const navigate = useNavigate()
  const redirectToLogin = useSessionRedirect()
  const [captured, setCaptured] = useState<string | null>(null) // thumbnail data URL
  const [matching, setMatching] = useState(false) // upload + match in flight
  const [results, setResults] = useState<Card[] | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [manualQuery, setManualQuery] = useState('')

  // Shared add-to-portfolio flow, same as Search/CardDetail
  const { add, busy: addBusy, status: addStatus } = useAddCard()
  const [adding, setAdding] = useState<string | null>(null)
  const [purchasePrice, setPurchasePrice] = useState('')
  const [quantity, setQuantity] = useState('1')

  function handleCapture(canvas: HTMLCanvasElement) {
    setCaptured(canvas.toDataURL('image/jpeg', 0.85))
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

  if (!getToken()) {
    return (
      <PageMessage action={{ to: '/login', label: 'Login', className: 'btn-primary btn-lg' }}>
        <h2>Log in to scan cards</h2>
        <p>Point your camera at a card to identify it and add it to your portfolio.</p>
      </PageMessage>
    )
  }

  return (
    <div className="page">
      <h1>Scan a card</h1>

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
    </div>
  )
}
