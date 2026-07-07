import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { getCard, getCardPrice, addCard, getToken, type Card } from '../api'

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

function money(value?: number) {
  return value != null ? `$${value.toFixed(2)}` : '—'
}

export default function CardDetail() {
  const { cardId } = useParams<{ cardId: string }>()
  const [card, setCard] = useState<Card | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [purchasePrice, setPurchasePrice] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [addStatus, setAddStatus] = useState<{ msg: string; ok: boolean } | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    if (!cardId) return
    let cancelled = false
    getCard(cardId)
      .then(data => {
        if (cancelled) return
        setCard(data)
        const market = getCardPrice(data)
        if (market != null) setPurchasePrice(market.toFixed(2))
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

  async function handleAdd() {
    if (!card) return
    if (!getToken()) {
      navigate('/login')
      return
    }
    try {
      const price = parseFloat(purchasePrice)
      const msg = await addCard(card.id, Number.isNaN(price) ? null : price, parseInt(quantity) || 1)
      setAddStatus({ msg, ok: true })
      setTimeout(() => setAddStatus(null), 3000)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to add card'
      setAddStatus({ msg, ok: false })
      setTimeout(() => setAddStatus(null), 3000)
    }
  }

  if (loading) return <div className="page centered"><p>Loading card...</p></div>
  if (error || !card) {
    return (
      <div className="page centered">
        <p className="error">{error || 'Card not found.'}</p>
        <Link to="/search" className="btn-primary" style={{ marginTop: '16px' }}>Back to Search</Link>
      </div>
    )
  }

  const priceEntries = Object.entries(card.tcgplayer?.prices ?? {})

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

          <div className="detail-facts">
            {card.rarity && (
              <div className="price-row">
                <span className="stat-label">Rarity</span>
                <span>{card.rarity}</span>
              </div>
            )}
            {card.types && card.types.length > 0 && (
              <div className="price-row">
                <span className="stat-label">Type</span>
                <span>{card.types.join(', ')}</span>
              </div>
            )}
            {card.hp && (
              <div className="price-row">
                <span className="stat-label">HP</span>
                <span>{card.hp}</span>
              </div>
            )}
            {card.artist && (
              <div className="price-row">
                <span className="stat-label">Artist</span>
                <span>{card.artist}</span>
              </div>
            )}
            {card.set.releaseDate && (
              <div className="price-row">
                <span className="stat-label">Released</span>
                <span>{card.set.releaseDate}</span>
              </div>
            )}
          </div>

          <h2>Market Prices</h2>
          {priceEntries.length === 0 ? (
            <p className="prices-note">Market prices aren't available for this card yet.</p>
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

          <h2>Add to Portfolio</h2>
          {addStatus ? (
            <p className={addStatus.ok ? 'success-msg' : 'error'}>{addStatus.msg}</p>
          ) : (
            <div className="detail-add-form">
              <label className="edit-field">
                <span className="stat-label">Price paid ($)</span>
                <input
                  type="number"
                  value={purchasePrice}
                  onChange={e => setPurchasePrice(e.target.value)}
                  className="mini-input"
                  min="0"
                  step="0.01"
                />
              </label>
              <label className="edit-field">
                <span className="stat-label">Quantity</span>
                <input
                  type="number"
                  value={quantity}
                  onChange={e => setQuantity(e.target.value)}
                  className="mini-input mini-qty"
                  min="1"
                />
              </label>
              <button className="btn-primary" onClick={handleAdd}>+ Portfolio</button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
