import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getPortfolio, removeCard, getToken, getCardImageUrl, type PortfolioCard } from '../api'

export default function Portfolio() {
  const [cards, setCards] = useState<PortfolioCard[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!getToken()) {
      setLoading(false)
      return
    }
    getPortfolio()
      .then(setCards)
      .catch(() => setError('Failed to load portfolio.'))
      .finally(() => setLoading(false))
  }, [])

  async function handleRemove(id: number, name: string) {
    if (!confirm(`Remove ${name} from your portfolio?`)) return
    try {
      await removeCard(id)
      setCards(prev => prev.filter(c => c.id !== id))
    } catch {
      alert('Failed to remove card.')
    }
  }

  if (!getToken()) {
    return (
      <div className="page centered">
        <h2>Log in to view your portfolio</h2>
        <p>Track your cards and monitor their value over time.</p>
        <Link to="/login" className="btn-primary btn-lg" style={{ marginTop: '16px' }}>Login</Link>
      </div>
    )
  }

  if (loading) return <div className="page centered"><p>Loading portfolio...</p></div>
  if (error) return <div className="page centered"><p className="error">{error}</p></div>

  const totalValue = cards.reduce((sum, c) => sum + (c.current_price ?? c.purchase_price) * c.quantity, 0)
  const totalCost = cards.reduce((sum, c) => sum + c.purchase_price * c.quantity, 0)
  const totalGainLoss = cards.reduce((sum, c) => sum + (c.gain_loss ?? 0), 0)

  return (
    <div className="page">
      <h1>My Portfolio</h1>

      {cards.length === 0 ? (
        <div className="centered">
          <p>No cards yet.</p>
          <Link to="/search" className="btn-primary" style={{ marginTop: '16px' }}>Search Cards</Link>
        </div>
      ) : (
        <>
          <div className="portfolio-summary">
            <div className="summary-stat">
              <span className="stat-label">Total Value</span>
              <span className="stat-value">${totalValue.toFixed(2)}</span>
            </div>
            <div className="summary-stat">
              <span className="stat-label">Total Cost</span>
              <span className="stat-value">${totalCost.toFixed(2)}</span>
            </div>
            <div className="summary-stat">
              <span className="stat-label">Gain / Loss</span>
              <span className={`stat-value ${totalGainLoss >= 0 ? 'positive' : 'negative'}`}>
                {totalGainLoss >= 0 ? '+' : ''}${totalGainLoss.toFixed(2)}
              </span>
            </div>
            <div className="summary-stat">
              <span className="stat-label">Cards</span>
              <span className="stat-value">{cards.length}</span>
            </div>
          </div>

          <div className="portfolio-grid">
            {cards.map(card => (
              <div key={card.id} className="portfolio-card">
                <img
                  src={getCardImageUrl(card.card_id)}
                  alt={card.card_name}
                  className="card-image"
                  loading="lazy"
                  onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                />
                <div className="portfolio-card-body">
                  <p className="card-name">{card.card_name}</p>
                  <p className="card-set">Qty: {card.quantity}</p>
                  <div className="price-rows">
                    <div className="price-row">
                      <span className="stat-label">Paid</span>
                      <span>${card.purchase_price.toFixed(2)}</span>
                    </div>
                    <div className="price-row">
                      <span className="stat-label">Now</span>
                      <span>{card.current_price != null ? `$${card.current_price.toFixed(2)}` : '—'}</span>
                    </div>
                    {card.gain_loss != null && (
                      <div className="price-row">
                        <span className="stat-label">P&L</span>
                        <span className={card.gain_loss >= 0 ? 'positive' : 'negative'}>
                          {card.gain_loss >= 0 ? '+' : ''}${card.gain_loss.toFixed(2)}
                          {card.gain_loss_pct != null && (
                            <span className="pct"> ({card.gain_loss_pct > 0 ? '+' : ''}{card.gain_loss_pct}%)</span>
                          )}
                        </span>
                      </div>
                    )}
                  </div>
                  <button
                    className="btn-outline btn-sm btn-danger"
                    onClick={() => handleRemove(card.id, card.card_name)}
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
