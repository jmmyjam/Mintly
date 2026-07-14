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
    getCard(cardId)
      .then(data => {
        if (cancelled) return
        setCard(data)
        setEbay(null)  // drop any prior card's estimate (in a callback, not the effect body)
        const market = getCardPrice(data)
        if (market != null) {
          setPurchasePrice(market.toFixed(2))
          return
        }
        // No TCGPlayer price — fall back to a recent-eBay-sold estimate, and
        // seed the add form with its median so the card can still be added
        return getEbayEstimate(data.id)
          .then(est => {
            if (cancelled) return
            setEbay(est)
            if (est.median != null) setPurchasePrice(est.median.toFixed(2))
          })
          .catch(() => {})
      })
      .catch(() => {
        if (!cancelled) setError('Card not found.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
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
