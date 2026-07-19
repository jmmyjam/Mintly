import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getCard, getCardPrice, getEbayEstimate, type Card, type EbayEstimate as Estimate } from '../api'
import DayChange from '../components/DayChange'
import EbayEstimate from '../components/EbayEstimate'
import PageMessage from '../components/PageMessage'
import PriceHistoryChart from '../components/PriceHistoryChart'
import PriceQtyForm from '../components/PriceQtyForm'
import StatRow from '../components/StatRow'
import StatusMessage from '../components/StatusMessage'
import StructuredData from '../components/StructuredData'
import { useAddCard } from '../hooks'
import { money } from '../format'

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

// Must match the static <title> in index.html — restored when leaving the page
const DEFAULT_TITLE = 'Mintly — Pokémon TCG Portfolio Tracker'

// schema.org Product markup for the card. Only facts visible on the page: the
// offer (price + TCGPlayer listing link) is included only when a real
// TCGPlayer market price exists — an eBay estimate is not an offer.
function cardJsonLd(card: Card, market: number | null) {
  const num = card.number
    ? ` #${card.number}${card.set.printedTotal ? `/${card.set.printedTotal}` : ''}`
    : ''
  const data: Record<string, unknown> = {
    '@context': 'https://schema.org',
    '@type': 'Product',
    name: card.name,
    image: [card.images.large],
    description:
      `${card.name} — Pokémon TCG card from ${card.set.name}${num}` +
      `${card.rarity ? `, ${card.rarity}` : ''}. Live market price and price history on Mintly.`,
    sku: card.id,
    brand: { '@type': 'Brand', name: 'Pokémon TCG' },
  }
  if (market != null && card.tcgplayer?.url) {
    data.offers = {
      '@type': 'Offer',
      url: card.tcgplayer.url,
      price: market.toFixed(2),
      priceCurrency: 'USD',
      seller: { '@type': 'Organization', name: 'TCGplayer' },
    }
  }
  return data
}

export default function CardDetail() {
  const { cardId } = useParams<{ cardId: string }>()
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

  return (
    <div className="page">
      <StructuredData data={cardJsonLd(card, market)} />
      <Link to="/search" className="back-link">← Back to Search</Link>

      <div className="detail-layout">
        <img src={card.images.large} alt={card.name} className="detail-image" />

        <div className="detail-info">
          <h1>{card.name}</h1>
          <p className="card-set">
            {card.set.name}
            {card.set.series ? ` · ${card.set.series}` : ''}
            {card.number ? ` · #${card.number}${card.set.printedTotal ? `/${card.set.printedTotal}` : ''}` : ''}
          </p>

          {market != null && (
            <div className="detail-price-head">
              <span className="detail-current-price">{money(market)}</span>
              {card.priceChange ? (
                <DayChange change={card.priceChange} />
              ) : (
                <span className="day-change-none">market price</span>
              )}
            </div>
          )}

          <div className="detail-facts">
            {card.rarity && <StatRow label="Rarity">{card.rarity}</StatRow>}
            {card.types && card.types.length > 0 && (
              <StatRow label="Type">{card.types.join(', ')}</StatRow>
            )}
            {card.hp && <StatRow label="HP">{card.hp}</StatRow>}
            {card.artist && <StatRow label="Artist">{card.artist}</StatRow>}
            {card.set.releaseDate && (
              <StatRow label="Released">{card.set.releaseDate}</StatRow>
            )}
          </div>

          {ebay && <EbayEstimate estimate={ebay} />}

          <h2>Market Prices</h2>
          {priceEntries.length === 0 ? (
            <p className="prices-note">
              TCGplayer market prices aren't available for this card
              {ebay && ebay.count > 0 ? ' — see the recent eBay sales above.' : ' yet.'}
            </p>
          ) : (
            <table className="price-table">
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
          )}
          {card.tcgplayer?.updatedAt && priceEntries.length > 0 && (
            <p className="prices-note">Prices from TCGPlayer, updated {card.tcgplayer.updatedAt}</p>
          )}

          <PriceHistoryChart key={card.id} cardId={card.id} />

          <h2>Add to Portfolio</h2>
          {addStatus ? (
            <StatusMessage ok={addStatus.ok}>{addStatus.msg}</StatusMessage>
          ) : (
            <PriceQtyForm
              className="detail-add-form"
              labeled
              price={purchasePrice}
              quantity={quantity}
              onPriceChange={setPurchasePrice}
              onQuantityChange={setQuantity}
              onSubmit={() => add(card.id, purchasePrice, quantity)}
              submitLabel="+ Portfolio"
              busyLabel="Adding..."
              busy={addBusy}
            />
          )}
        </div>
      </div>
    </div>
  )
}
