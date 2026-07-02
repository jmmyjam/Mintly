import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { getPortfolio, getPortfolioHistory, removeCard, updateCard, getToken, getCardImageUrl, type PortfolioCard, type HistoryPoint } from '../api'

function formatChartDate(d: string) {
  return new Date(d + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function localISODate(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export default function Portfolio() {
  const [cards, setCards] = useState<PortfolioCard[]>([])
  const [history, setHistory] = useState<HistoryPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editPrice, setEditPrice] = useState('')
  const [editQty, setEditQty] = useState('')

  useEffect(() => {
    if (!getToken()) {
      setLoading(false)
      return
    }
    getPortfolio()
      .then(loaded => {
        setCards(loaded)
        // fetch after the portfolio loads so today's snapshot is included
        return getPortfolioHistory().then(setHistory).catch(() => {})
      })
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

  function startEdit(card: PortfolioCard) {
    setEditingId(card.id)
    setEditPrice(String(card.purchase_price))
    setEditQty(String(card.quantity))
  }

  async function handleSaveEdit(card: PortfolioCard) {
    const price = parseFloat(editPrice)
    const qty = parseInt(editQty)
    if (Number.isNaN(price) || price < 0 || Number.isNaN(qty) || qty < 1) {
      alert('Enter a valid price and quantity.')
      return
    }
    try {
      await updateCard(card.id, { purchase_price: price, quantity: qty })
      setCards(prev => prev.map(c => {
        if (c.id !== card.id) return c
        const gain_loss = c.current_price != null ? Math.round((c.current_price - price) * qty * 100) / 100 : null
        const gain_loss_pct = c.current_price != null && price > 0
          ? Math.round(((c.current_price - price) / price) * 10000) / 100
          : null
        return { ...c, purchase_price: price, quantity: qty, gain_loss, gain_loss_pct }
      }))
      setEditingId(null)
    } catch {
      alert('Failed to update card.')
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

  // With under two days of history, show a flat line at the current value
  const isPlaceholder = history.length < 2
  let chartData = history
  if (isPlaceholder) {
    const today = new Date()
    const yesterday = new Date(today)
    yesterday.setDate(today.getDate() - 1)
    chartData = [
      { date: localISODate(yesterday), total_value: totalValue },
      { date: localISODate(today), total_value: totalValue },
    ]
  }

  const chart = (
    <div className="portfolio-chart">
      <h2>Value Over Time</h2>
      {isPlaceholder && (
        <p className="chart-caption">Showing today's value — history builds each day you visit.</p>
      )}
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="valueFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.3} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={formatChartDate}
            stroke="var(--text)"
            fontSize={12}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tickFormatter={v => `$${v}`}
            stroke="var(--text)"
            fontSize={12}
            tickLine={false}
            axisLine={false}
            width={60}
            domain={['auto', 'auto']}
          />
          <Tooltip
            formatter={value => [`$${Number(value).toFixed(2)}`, 'Value']}
            labelFormatter={label => formatChartDate(String(label))}
            contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8 }}
            labelStyle={{ color: 'var(--text)' }}
          />
          <Area type="monotone" dataKey="total_value" stroke="var(--accent)" strokeWidth={2} fill="url(#valueFill)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )

  return (
    <div className="page">
      <h1>My Portfolio</h1>

      {cards.length === 0 ? (
        <>
          {chart}
          <div className="centered">
            <p>No cards yet.</p>
            <Link to="/search" className="btn-primary" style={{ marginTop: '16px' }}>Search Cards</Link>
          </div>
        </>
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

          {chart}

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
                  {editingId === card.id ? (
                    <div className="add-form">
                      <label className="edit-field">
                        <span className="stat-label">Price paid ($)</span>
                        <input
                          type="number"
                          value={editPrice}
                          onChange={e => setEditPrice(e.target.value)}
                          className="mini-input"
                          min="0"
                          step="0.01"
                        />
                      </label>
                      <label className="edit-field">
                        <span className="stat-label">Quantity</span>
                        <input
                          type="number"
                          value={editQty}
                          onChange={e => setEditQty(e.target.value)}
                          className="mini-input mini-qty"
                          min="1"
                        />
                      </label>
                      <div className="add-form-buttons">
                        <button className="btn-primary btn-sm" onClick={() => handleSaveEdit(card)}>
                          Save
                        </button>
                        <button className="btn-outline btn-sm" onClick={() => setEditingId(null)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
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
                      <div className="card-actions">
                        <button className="btn-outline btn-sm" onClick={() => startEdit(card)}>
                          Edit
                        </button>
                        <button
                          className="btn-outline btn-sm btn-danger"
                          onClick={() => handleRemove(card.id, card.card_name)}
                        >
                          Remove
                        </button>
                      </div>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
