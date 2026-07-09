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

function formatLotDate(d: string) {
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// One card can have several lots — separate purchases at different prices
interface CardGroup {
  card_id: string
  card_name: string
  current_price: number | null
  lots: PortfolioCard[]
}

function groupByCard(cards: PortfolioCard[]): CardGroup[] {
  const map = new Map<string, CardGroup>()
  for (const c of cards) {
    const group = map.get(c.card_id)
    if (group) {
      group.lots.push(c)
    } else {
      map.set(c.card_id, {
        card_id: c.card_id,
        card_name: c.card_name,
        current_price: c.current_price,
        lots: [c],
      })
    }
  }
  return [...map.values()]
}

export default function Portfolio() {
  const [cards, setCards] = useState<PortfolioCard[]>([])
  const [history, setHistory] = useState<HistoryPoint[]>([])
  const [loading, setLoading] = useState(() => !!getToken())
  const [error, setError] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editPrice, setEditPrice] = useState('')
  const [editQty, setEditQty] = useState('')

  useEffect(() => {
    if (!getToken()) return
    getPortfolio()
      .then(loaded => {
        // show the portfolio immediately; the chart fills in when history arrives
        setCards(loaded)
        setLoading(false)
        // fetch after the portfolio loads so today's snapshot is included
        return getPortfolioHistory().then(setHistory).catch(() => {})
      })
      .catch(err => {
        setError(err instanceof Error ? err.message : 'Failed to load portfolio.')
        setLoading(false)
      })
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

  function startEdit(lot: PortfolioCard) {
    setEditingId(lot.id)
    setEditPrice(String(lot.purchase_price))
    setEditQty(String(lot.quantity))
  }

  async function handleSaveEdit(lot: PortfolioCard) {
    const price = parseFloat(editPrice)
    const qty = parseInt(editQty)
    if (Number.isNaN(price) || price < 0 || Number.isNaN(qty) || qty < 1) {
      alert('Enter a valid price and quantity.')
      return
    }
    try {
      await updateCard(lot.id, { purchase_price: price, quantity: qty })
      setCards(prev => prev.map(c => {
        if (c.id !== lot.id) return c
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
  const groups = groupByCard(cards)

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

  const editForm = (lot: PortfolioCard) => (
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
        <button className="btn-primary btn-sm" onClick={() => handleSaveEdit(lot)}>
          Save
        </button>
        <button className="btn-outline btn-sm" onClick={() => setEditingId(null)}>
          Cancel
        </button>
      </div>
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
              <span className="stat-value">{groups.length}</span>
            </div>
          </div>

          {chart}

          <div className="portfolio-grid">
            {groups.map(group => {
              const single = group.lots.length === 1
              const totalQty = group.lots.reduce((sum, l) => sum + l.quantity, 0)
              const groupCost = group.lots.reduce((sum, l) => sum + l.purchase_price * l.quantity, 0)
              const avgPaid = totalQty > 0 ? groupCost / totalQty : 0
              const groupGain = group.current_price != null
                ? group.lots.reduce((sum, l) => sum + (l.gain_loss ?? 0), 0)
                : null
              const groupGainPct = groupGain != null && groupCost > 0
                ? Math.round((groupGain / groupCost) * 10000) / 100
                : null
              const isExpanded = expandedId === group.card_id
              const lot = group.lots[0]

              return (
                <div key={group.card_id} className="portfolio-card">
                  <Link to={`/card/${group.card_id}`} className="card-link">
                    <img
                      src={getCardImageUrl(group.card_id)}
                      alt={group.card_name}
                      className="card-image"
                      loading="lazy"
                      onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                    />
                  </Link>
                  <div className="portfolio-card-body">
                    <Link to={`/card/${group.card_id}`} className="card-link">
                      <p className="card-name">{group.card_name}</p>
                    </Link>
                    <p className="card-set">Qty: {totalQty}{!single ? ` · ${group.lots.length} purchases` : ''}</p>

                    {single && editingId === lot.id ? (
                      editForm(lot)
                    ) : (
                      <>
                        <div className="price-rows">
                          <div className="price-row">
                            <span className="stat-label">{single ? 'Paid' : 'Avg Paid'}</span>
                            <span>${(single ? lot.purchase_price : avgPaid).toFixed(2)}</span>
                          </div>
                          <div className="price-row">
                            <span className="stat-label">Now</span>
                            <span>{group.current_price != null ? `$${group.current_price.toFixed(2)}` : '—'}</span>
                          </div>
                          {groupGain != null && (
                            <div className="price-row">
                              <span className="stat-label">P&L</span>
                              <span className={groupGain >= 0 ? 'positive' : 'negative'}>
                                {groupGain >= 0 ? '+' : ''}${groupGain.toFixed(2)}
                                {groupGainPct != null && (
                                  <span className="pct"> ({groupGainPct > 0 ? '+' : ''}{groupGainPct}%)</span>
                                )}
                              </span>
                            </div>
                          )}
                        </div>

                        {single ? (
                          <div className="card-actions">
                            <button className="btn-outline btn-sm" onClick={() => startEdit(lot)}>
                              Edit
                            </button>
                            <button
                              className="btn-outline btn-sm btn-danger"
                              onClick={() => handleRemove(lot.id, group.card_name)}
                            >
                              Remove
                            </button>
                          </div>
                        ) : (
                          <>
                            <button
                              className="btn-outline btn-sm"
                              onClick={() => setExpandedId(isExpanded ? null : group.card_id)}
                            >
                              {isExpanded ? 'Hide purchases ▴' : `${group.lots.length} purchases ▾`}
                            </button>
                            {isExpanded && (
                              <div className="lot-list">
                                {group.lots.map(l =>
                                  editingId === l.id ? (
                                    <div key={l.id}>{editForm(l)}</div>
                                  ) : (
                                    <div key={l.id} className="lot-row">
                                      <div className="lot-info">
                                        <span className="lot-main">{l.quantity} @ ${l.purchase_price.toFixed(2)}</span>
                                        <span className="lot-date">{formatLotDate(l.purchase_date)}</span>
                                      </div>
                                      {l.gain_loss != null && (
                                        <span className={l.gain_loss >= 0 ? 'positive' : 'negative'}>
                                          {l.gain_loss >= 0 ? '+' : ''}${l.gain_loss.toFixed(2)}
                                        </span>
                                      )}
                                      <div className="lot-actions">
                                        <button className="lot-btn" onClick={() => startEdit(l)}>Edit</button>
                                        <button
                                          className="lot-btn lot-btn-danger"
                                          onClick={() => handleRemove(l.id, group.card_name)}
                                        >
                                          ✕
                                        </button>
                                      </div>
                                    </div>
                                  )
                                )}
                              </div>
                            )}
                          </>
                        )}
                      </>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
