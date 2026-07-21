import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { getCard, getCardPrice, getEbayEstimate, type Card, type EbayEstimate as Estimate } from '../api'
import CardImage from '../components/CardImage'
import DayChange from '../components/DayChange'
import PageMessage from '../components/PageMessage'
import PriceHistoryChart from '../components/PriceHistoryChart'
import PriceQtyForm from '../components/PriceQtyForm'
import StatusMessage from '../components/StatusMessage'
import StructuredData from '../components/StructuredData'
import { useAddCard } from '../hooks'
import { money } from '../format'
import styles from './CardDetail.module.css'

const VARIANT_LABELS: { [key: string]: string } = {
  normal: 'Normal',
  holofoil: 'Holofoil',
  reverseHolofoil: 'Reverse Holofoil',
  '1stEditionHolofoil': '1st Edition Holofoil',
  '1stEditionNormal': '1st Edition Normal',
  unlimitedHolofoil: 'Unlimited Holofoil',
}

function variantLabel(key: string) {
  return VARIANT_LABELS[key] || key
}

// Matches getCardPrice's variant preference — the tile row + hero price both
// describe this "primary" variant.
const PRICE_PREF = ['holofoil', 'normal', 'reverseHolofoil', '1stEditionHolofoil']

function formatDate(d: string) {
  return new Date(d + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function dateRange(since: string, until: string) {
  return since === until ? formatDate(until) : `${formatDate(since)} – ${formatDate(until)}`
}

// Must match the static <title> in index.html — restored when leaving the page
const DEFAULT_TITLE = 'Mintly — Pokémon TCG Portfolio Tracker'

// schema.org Product markup — describes the card so it can surface in search.
// Mintly is a tracker, not a store, so there is deliberately NO `offers` block:
// the prices shown are third-party market/estimate figures, not our listings.
function cardJsonLd(card: Card) {
  const num = card.number
    ? ` #${card.number}${card.set.printedTotal ? `/${card.set.printedTotal}` : ''}`
    : ''
  return {
    '@context': 'https://schema.org',
    '@type': 'Product',
    name: card.name,
    image: [card.images.large],
    description:
      `${card.name} — Pokémon TCG card from ${card.set.name}${num}` +
      `${card.rarity ? `, ${card.rarity}` : ''}. Market price and price history on Mintly.`,
    sku: card.id,
    brand: { '@type': 'Brand', name: 'Pokémon TCG' },
  }
}

export default function CardDetail() {
  const { cardId } = useParams<{ cardId: string }>()
  const location = useLocation()
  // Search stashes the query it was showing in link state, so "Back to Search"
  // returns to that exact search rather than the default view (falls back to a
  // bare /search when arriving from elsewhere, e.g. a portfolio tile).
  const backSearch = (location.state as { backSearch?: string } | null)?.backSearch ?? ''
  const [card, setCard] = useState<Card | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [purchasePrice, setPurchasePrice] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [ebay, setEbay] = useState<Estimate | null>(null)
  const { add, busy: addBusy, status: addStatus } = useAddCard()

  useEffect(() => {
    if (!cardId) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let autoPrice = ''  // the last price we auto-filled — only ever overwrite that

    // Seed the add form, but never clobber a price the user typed themselves
    const seedPrice = (value: number) => {
      const next = value.toFixed(2)
      setPurchasePrice(prev => (prev === '' || prev === autoPrice ? next : prev))
      autoPrice = next
    }

    const load = (attempt: number) => {
      getCard(cardId)
        .then(data => {
          if (cancelled) return
          setCard(data)
          document.title = `${data.name} · ${data.set.name} — Mintly`
          if (attempt === 0) setEbay(null)  // drop any prior card's estimate (in a callback, not the effect body)
          const market = getCardPrice(data)
          if (market != null) {
            seedPrice(market)
          } else if (attempt === 0) {
            // No TCGPlayer price — fall back to a recent-eBay-sold estimate, and
            // seed the add form with its median so the card can still be added
            getEbayEstimate(data.id)
              .then(est => {
                if (cancelled) return
                setEbay(est)
                if (est.median != null) seedPrice(est.median)
              })
              .catch(() => {})
          }
          // The backend served a stale catalog price and is re-fetching it in
          // the background — re-poll a few times so the fresh number lands
          // on the page without a reload
          if (data.refreshing && attempt < 3) {
            timer = setTimeout(() => load(attempt + 1), 3000)
          }
        })
        .catch(() => {
          if (!cancelled && attempt === 0) setError('Card not found.')
        })
        .finally(() => {
          if (!cancelled && attempt === 0) setLoading(false)
        })
    }

    load(0)
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
      document.title = DEFAULT_TITLE
    }
  }, [cardId])

  if (loading) return <PageMessage><p>Loading card...</p></PageMessage>
  if (error || !card) {
    return (
      <PageMessage action={{ to: '/search', label: 'Back to Search' }}>
        <p className="error">{error || 'Card not found.'}</p>
      </PageMessage>
    )
  }

  const priceEntries = Object.entries(card.tcgplayer?.prices ?? {})
  const market = getCardPrice(card)
  const hasMarket = market != null

  // Primary TCGPlayer variant (drives the tile row); eBay value prefers the
  // freshly-scraped median, falling back to the stored snapshot for an instant
  // number while the live scrape lands.
  const primaryKey = PRICE_PREF.find(k => card.tcgplayer?.prices?.[k]) ?? priceEntries[0]?.[0]
  const primary = primaryKey ? card.tcgplayer?.prices?.[primaryKey] : undefined
  const ebayValue = ebay?.median ?? card.estimate?.value ?? null
  const heroValue = hasMarket ? market : ebayValue

  // KPI stat tiles adapt to the price source
  const tiles: { label: string; value: number | null | undefined }[] =
    hasMarket && primary
      ? [
          { label: 'Market', value: market },
          { label: 'Low', value: primary.low },
          { label: 'Mid', value: primary.mid },
          { label: 'High', value: primary.high },
        ]
      : !hasMarket && ebay && ebay.count > 0
      ? [
          { label: 'Median', value: ebay.median },
          { label: 'Average', value: ebay.average },
          { label: 'Low', value: ebay.low },
          { label: 'High', value: ebay.high },
        ]
      : []

  return (
    <div className="page">
      <StructuredData data={cardJsonLd(card)} />
      <Link to={{ pathname: '/search', search: backSearch }} className={styles.backLink}>← Back to Search</Link>

      <div className={styles.detailLayout}>
        <div className={styles.media}>
          <CardImage src={card.images.large} alt={card.name} size="detail" eager />
        </div>

        <div className={styles.info}>
          <div>
            <h1>{card.name}</h1>
            <p className={styles.meta}>
              {card.set.name}
              {card.set.series ? ` · ${card.set.series}` : ''}
              {card.number ? ` · #${card.number}${card.set.printedTotal ? `/${card.set.printedTotal}` : ''}` : ''}
            </p>
          </div>

          <div className={styles.priceBlock}>
            <div className={styles.priceRow}>
              {heroValue != null ? (
                <>
                  <span className={styles.price}>{money(heroValue)}</span>
                  {card.priceChange && <DayChange change={card.priceChange} />}
                  <span className={`${styles.source}${hasMarket ? '' : ` ${styles.sourceEbay}`}`}>
                    {hasMarket ? 'TCGplayer market' : 'eBay est.'}
                  </span>
                </>
              ) : (
                <span className={styles.priceNone}>
                  {!hasMarket && ebay && ebay.count === 0 ? 'No recent sale price' : 'Checking price…'}
                </span>
              )}
            </div>
            {!hasMarket && (
              ebay && ebay.count > 0 ? (
                <p className={styles.disclaimer}>
                  Estimated from {ebay.count} recent eBay sold listings
                  {ebay.since && ebay.until ? ` · ${dateRange(ebay.since, ebay.until)}` : ''} · informational only.{' '}
                  <a href={ebay.source_url} target="_blank" rel="noopener noreferrer">View on eBay</a>
                </p>
              ) : ebay && ebay.count === 0 ? (
                <p className={styles.disclaimer}>
                  No recent eBay sales found for this card.{' '}
                  <a href={ebay.source_url} target="_blank" rel="noopener noreferrer">Search eBay</a>
                </p>
              ) : (
                <p className={styles.disclaimer}>Estimating value from recent eBay sold listings…</p>
              )
            )}
          </div>

          <div className={styles.buyBox}>
            <p className={styles.buyTitle}>Add to Portfolio</p>
            {addStatus ? (
              <StatusMessage ok={addStatus.ok}>{addStatus.msg}</StatusMessage>
            ) : (
              <PriceQtyForm
                className={styles.buyForm}
                labeled
                price={purchasePrice}
                quantity={quantity}
                onPriceChange={setPurchasePrice}
                onQuantityChange={setQuantity}
                onSubmit={() => add(card.id, purchasePrice, quantity)}
                submitLabel="+ Add to Portfolio"
                busyLabel="Adding..."
                busy={addBusy}
              />
            )}
          </div>

          {tiles.length > 0 && (
            <div>
              <div className={styles.tiles}>
                {tiles.map(t => (
                  <div key={t.label} className={styles.tile}>
                    <span className={styles.tileLabel}>{t.label}</span>
                    <span className={styles.tileValue}>{money(t.value)}</span>
                  </div>
                ))}
              </div>
              {hasMarket && card.tcgplayer?.updatedAt && (
                <p className={styles.tilesCaption}>Prices from TCGplayer · updated {card.tcgplayer.updatedAt}</p>
              )}
            </div>
          )}

          <div className={styles.chips}>
            {card.rarity && <span className={styles.chip}>{card.rarity}</span>}
            {card.types?.map(t => <span key={t} className={styles.chip}>{t}</span>)}
            {card.hp && <span className={styles.chip}>HP <b>{card.hp}</b></span>}
            {card.artist && <span className={styles.chip}>Artist <b>{card.artist}</b></span>}
            {card.set.releaseDate && <span className={styles.chip}>Released {card.set.releaseDate}</span>}
          </div>
        </div>
      </div>

      <div className={styles.below}>
        <PriceHistoryChart key={card.id} cardId={card.id} currentPrice={heroValue} />

        {priceEntries.length > 1 && (
          <div className={styles.variants}>
            <h2>All price variants</h2>
            <div className={styles.tableScroll}>
              <table className={styles.priceTable}>
                <thead>
                  <tr>
                    <th>Variant</th>
                    <th>Low</th>
                    <th>Mid</th>
                    <th>High</th>
                    <th>Market</th>
                  </tr>
                </thead>
                <tbody>
                  {priceEntries.map(([variant, prices]) => (
                    <tr key={variant}>
                      <td>{variantLabel(variant)}</td>
                      <td>{money(prices.low)}</td>
                      <td>{money(prices.mid)}</td>
                      <td>{money(prices.high)}</td>
                      <td>{money(prices.market)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {card.tcgplayer?.updatedAt && (
              <p className={styles.updated}>Prices from TCGplayer, updated {card.tcgplayer.updatedAt}</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
