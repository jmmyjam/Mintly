import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { getPortfolio, getPortfolioHistory, removeCard, updateCard, getToken, getCardImageUrl, CONNECTION_ERROR, SessionExpiredError, type PortfolioCard, type HistoryPoint, type PriceChange } from '../api'
import CardImage from '../components/CardImage'
import DayChange from '../components/DayChange'
import GainLoss from '../components/GainLoss'
import PageMessage from '../components/PageMessage'
import PriceQtyForm from '../components/PriceQtyForm'
import SignedOutHero from '../components/SignedOutHero'
import StatRow from '../components/StatRow'
import StatusMessage from '../components/StatusMessage'
import { useSessionRedirect } from '../hooks'
import { money } from '../format'
import styles from './Portfolio.module.css'

// ----- Types & constants ---------------------------------------------------------

// One card can have several lots — separate purchases at different prices
interface CardGroup {
  card_id: string
  card_name: string
  current_price: number | null
  price_change: PriceChange | null
  image_url: string | null
  lots: PortfolioCard[]
}

type SortKey = 'recent' | 'value' | 'gain' | 'loss' | 'name'
type PLFilter = 'all' | 'gainers' | 'losers'

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'recent', label: 'Recently added' },
  { value: 'value', label: 'Highest value' },
  { value: 'gain', label: 'Biggest gain' },
  { value: 'loss', label: 'Biggest loss' },
  { value: 'name', label: 'Name A–Z' },
]

// ----- Helpers ---------------------------------------------------------------------

function formatChartDate(d: string) {
  return new Date(d + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function localISODate(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// purchase_date arrives as naive UTC with no zone suffix; anchor it with Z so
// it converts to the local date instead of being read as local time
function parseUTCDate(d: string) {
  return new Date(d.endsWith('Z') ? d : d + 'Z')
}

function formatLotDate(d: string) {
  return parseUTCDate(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
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
        price_change: c.price_change,
        image_url: c.image_url,
        lots: [c],
      })
    }
  }
  return [...map.values()]
}

// gain is null when the card has no market price (it can't be a gainer or loser)
function groupMetrics(g: CardGroup) {
  return {
    value: g.lots.reduce((s, l) => s + (l.current_price ?? l.purchase_price) * l.quantity, 0),
    gain: g.current_price != null ? g.lots.reduce((s, l) => s + (l.gain_loss ?? 0), 0) : null,
    added: Math.max(...g.lots.map(l => parseUTCDate(l.purchase_date).getTime() || 0)),
  }
}

export default function Portfolio() {
  const [cards, setCards] = useState<PortfolioCard[]>([])
  const [history, setHistory] = useState<HistoryPoint[]>([])
  const [loading, setLoading] = useState(() => !!getToken())
  const [error, setError] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('recent')
  const [nameFilter, setNameFilter] = useState('')
  const [plFilter, setPlFilter] = useState<PLFilter>('all')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editPrice, setEditPrice] = useState('')
  const [editQty, setEditQty] = useState('')
  const [confirmRemoveId, setConfirmRemoveId] = useState<number | null>(null)
  const [lotError, setLotError] = useState<{ id: number; text: string } | null>(null)
  // The token is already cleared by authedFetch — send the user back to login
  const redirectToLogin = useSessionRedirect()

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
        if (err instanceof SessionExpiredError) {
          redirectToLogin()
          return
        }
        setError(
          err instanceof TypeError
            ? CONNECTION_ERROR
            : "We couldn't load your portfolio right now. Please try again in a moment.",
        )
        setLoading(false)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Inline error line next to the affected lot; self-clears like useAddCard's errors
  function showLotError(id: number, text: string) {
    setLotError({ id, text })
    setTimeout(() => setLotError(null), 4000)
  }

  async function handleRemove(id: number) {
    setConfirmRemoveId(null)
    try {
      await removeCard(id)
      setCards(prev => prev.filter(c => c.id !== id))
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        redirectToLogin()
        return
      }
      showLotError(
        id,
        err instanceof TypeError ? CONNECTION_ERROR : "We couldn't remove that card. Please try again.",
      )
    }
  }

  function startEdit(lot: PortfolioCard) {
    setConfirmRemoveId(null)
    setEditingId(lot.id)
    setEditPrice(String(lot.purchase_price))
    setEditQty(String(lot.quantity))
  }

  async function handleSaveEdit(lot: PortfolioCard) {
    const price = parseFloat(editPrice)
    const qty = parseInt(editQty)
    if (Number.isNaN(price) || price < 0 || Number.isNaN(qty) || qty < 1) {
      showLotError(lot.id, 'Enter a valid price and quantity.')
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
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        redirectToLogin()
        return
      }
      showLotError(
        lot.id,
        err instanceof TypeError ? CONNECTION_ERROR : "We couldn't save those changes. Please try again.",
      )
    }
  }

  if (!getToken()) {
    return <SignedOutHero variant="portfolio" />
  }

  if (loading) return <PageMessage><p>Loading portfolio...</p></PageMessage>
  if (error) return <PageMessage><p className="error">{error}</p></PageMessage>

  const totalValue = cards.reduce((sum, c) => sum + (c.current_price ?? c.purchase_price) * c.quantity, 0)
  const totalCost = cards.reduce((sum, c) => sum + c.purchase_price * c.quantity, 0)
  const totalGainLoss = cards.reduce((sum, c) => sum + (c.gain_loss ?? 0), 0)
  const groups = groupByCard(cards)

  const metrics = new Map(groups.map(g => [g.card_id, groupMetrics(g)]))
  const nameQuery = nameFilter.trim().toLowerCase()
  const visibleGroups = groups.filter(g => {
    if (nameQuery && !g.card_name.toLowerCase().includes(nameQuery)) return false
    if (plFilter !== 'all') {
      const gain = metrics.get(g.card_id)!.gain
      if (gain == null) return false
      if (plFilter === 'gainers' ? gain < 0 : gain >= 0) return false
    }
    return true
  })
  visibleGroups.sort((a, b) => {
    const ma = metrics.get(a.card_id)!
    const mb = metrics.get(b.card_id)!
    switch (sortKey) {
      case 'value': return mb.value - ma.value
      case 'gain': return (mb.gain ?? -Infinity) - (ma.gain ?? -Infinity) // priceless cards last
      case 'loss': return (ma.gain ?? Infinity) - (mb.gain ?? Infinity)
      case 'name': return a.card_name.localeCompare(b.card_name)
      default: return mb.added - ma.added
    }
  })
  const isFiltered = !!nameQuery || plFilter !== 'all'

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
    <div className={styles.portfolioChart}>
      <h2>Value Over Time</h2>
      {isPlaceholder && (
        <p className={styles.chartCaption}>Showing today's value. History builds each day you visit.</p>
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
            formatter={value => [money(Number(value)), 'Value']}
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
    <PriceQtyForm
      labeled
      price={editPrice}
      quantity={editQty}
      onPriceChange={setEditPrice}
      onQuantityChange={setEditQty}
      onSubmit={() => handleSaveEdit(lot)}
      submitLabel="Save"
      smallButtons
      onCancel={() => setEditingId(null)}
    />
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
          <div className={styles.portfolioSummary}>
            <div className={styles.summaryStat}>
              <span className="stat-label">Total Value</span>
              <span className={styles.statValue}>{money(totalValue)}</span>
            </div>
            <div className={styles.summaryStat}>
              <span className="stat-label">Total Cost</span>
              <span className={styles.statValue}>{money(totalCost)}</span>
            </div>
            <div className={styles.summaryStat}>
              <span className="stat-label">Gain / Loss</span>
              <GainLoss value={totalGainLoss} className={styles.statValue} />
            </div>
            <div className={styles.summaryStat}>
              <span className="stat-label">Cards</span>
              <span className={styles.statValue}>{groups.length}</span>
            </div>
          </div>

          {chart}

          <div className="filter-row">
            <input
              value={nameFilter}
              onChange={e => setNameFilter(e.target.value)}
              placeholder="Filter by name"
              className={`filter-select ${styles.filterName}`}
            />
            <select
              value={plFilter}
              onChange={e => setPlFilter(e.target.value as PLFilter)}
              className="filter-select"
            >
              <option value="all">All cards</option>
              <option value="gainers">Gainers</option>
              <option value="losers">Losers</option>
            </select>
            <select
              value={sortKey}
              onChange={e => setSortKey(e.target.value as SortKey)}
              className="filter-select"
            >
              {SORT_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>Sort: {o.label}</option>
              ))}
            </select>
            {isFiltered && (
              <>
                <button
                  className="btn-outline btn-sm"
                  onClick={() => { setNameFilter(''); setPlFilter('all') }}
                >
                  Clear
                </button>
                <span className={styles.toolbarCount}>
                  {visibleGroups.length} of {groups.length} cards
                </span>
              </>
            )}
          </div>

          {visibleGroups.length === 0 ? (
            <p className={styles.noMatch}>No cards match your filters.</p>
          ) : (
          <div className={styles.portfolioGrid}>
            {visibleGroups.map(group => {
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
                <div key={group.card_id} className={styles.portfolioCard}>
                  <Link to={`/card/${group.card_id}`} className="card-link">
                    <CardImage src={group.image_url ?? getCardImageUrl(group.card_id)} alt={group.card_name} />
                  </Link>
                  <div className={styles.portfolioCardBody}>
                    <Link to={`/card/${group.card_id}`} className="card-link">
                      <p className="card-name">{group.card_name}</p>
                    </Link>
                    <p className="card-set">Qty: {totalQty}{!single ? ` · ${group.lots.length} purchases` : ''}</p>

                    {single && editingId === lot.id ? (
                      editForm(lot)
                    ) : (
                      <>
                        <div className="price-rows">
                          <StatRow label={single ? 'Paid' : 'Avg Paid'}>
                            {money(single ? lot.purchase_price : avgPaid)}
                          </StatRow>
                          <StatRow label="Now">
                            {money(group.current_price)}
                            {group.price_change && (
                              <DayChange change={group.price_change} className="stat-day-change" />
                            )}
                          </StatRow>
                          {groupGain != null && (
                            <StatRow label="P&L">
                              <GainLoss value={groupGain} pct={groupGainPct} />
                            </StatRow>
                          )}
                        </div>

                        {single ? (
                          confirmRemoveId === lot.id ? (
                            <div className={styles.cardActions}>
                              <button
                                className="btn-outline btn-sm btn-danger"
                                onClick={() => handleRemove(lot.id)}
                              >
                                Confirm remove
                              </button>
                              <button className="btn-outline btn-sm" onClick={() => setConfirmRemoveId(null)}>
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <div className={styles.cardActions}>
                              <button className="btn-outline btn-sm" onClick={() => startEdit(lot)}>
                                Edit
                              </button>
                              <button
                                className="btn-outline btn-sm btn-danger"
                                onClick={() => setConfirmRemoveId(lot.id)}
                              >
                                Remove
                              </button>
                            </div>
                          )
                        ) : (
                          <>
                            <button
                              className="btn-outline btn-sm"
                              onClick={() => setExpandedId(isExpanded ? null : group.card_id)}
                            >
                              {isExpanded ? 'Hide purchases ▴' : `${group.lots.length} purchases ▾`}
                            </button>
                            {isExpanded && (
                              <div className={styles.lotList}>
                                {group.lots.map(l => (
                                  <div key={l.id}>
                                    {editingId === l.id ? (
                                      editForm(l)
                                    ) : (
                                      <div className={styles.lotRow}>
                                        <div className={styles.lotInfo}>
                                          <span className={styles.lotMain}>{l.quantity} @ {money(l.purchase_price)}</span>
                                          <span className={styles.lotDate}>{formatLotDate(l.purchase_date)}</span>
                                        </div>
                                        {l.gain_loss != null && <GainLoss value={l.gain_loss} />}
                                        {confirmRemoveId === l.id ? (
                                          <div className={styles.lotActions}>
                                            <button
                                              className={`${styles.lotBtn} ${styles.lotBtnDanger} negative`}
                                              onClick={() => handleRemove(l.id)}
                                            >
                                              Remove
                                            </button>
                                            <button className={styles.lotBtn} onClick={() => setConfirmRemoveId(null)}>
                                              Cancel
                                            </button>
                                          </div>
                                        ) : (
                                          <div className={styles.lotActions}>
                                            <button className={styles.lotBtn} onClick={() => startEdit(l)}>Edit</button>
                                            <button
                                              className={`${styles.lotBtn} ${styles.lotBtnDanger}`}
                                              onClick={() => setConfirmRemoveId(l.id)}
                                            >
                                              ✕
                                            </button>
                                          </div>
                                        )}
                                      </div>
                                    )}
                                    {lotError?.id === l.id && (
                                      <StatusMessage ok={false}>{lotError.text}</StatusMessage>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}
                          </>
                        )}
                      </>
                    )}
                    {single && lotError?.id === lot.id && (
                      <StatusMessage ok={false}>{lotError.text}</StatusMessage>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
          )}
        </>
      )}
    </div>
  )
}
