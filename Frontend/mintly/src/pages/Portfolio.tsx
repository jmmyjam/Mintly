import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceDot, ResponsiveContainer } from 'recharts'
import { getPortfolio, getPortfolioHistory, getToken, getCardImageUrl, CONNECTION_ERROR, SessionExpiredError, type PortfolioCard, type HistoryPoint } from '../api'
import CardImage from '../components/CardImage'
import DayChange from '../components/DayChange'
import GainLoss from '../components/GainLoss'
import PageMessage from '../components/PageMessage'
import SignedOutHero from '../components/SignedOutHero'
import { useSessionRedirect } from '../hooks'
import { money, signedMoney } from '../format'
import { groupByCard, groupMetrics, localISODate, formatChartDate } from '../portfolio'
import styles from './Portfolio.module.css'

// ----- Types & constants ---------------------------------------------------------

type SortKey = 'recent' | 'value' | 'gain' | 'loss' | 'name'
type PLFilter = 'all' | 'gainers' | 'losers'
type Range = '1M' | '6M' | '1Y' | 'All'

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'recent', label: 'Recently added' },
  { value: 'value', label: 'Highest value' },
  { value: 'gain', label: 'Biggest gain' },
  { value: 'loss', label: 'Biggest loss' },
  { value: 'name', label: 'Name A–Z' },
]

const RANGES: Range[] = ['1M', '6M', '1Y', 'All']
const RANGE_DAYS: Record<Range, number | null> = { '1M': 30, '6M': 180, '1Y': 365, All: null }

export default function Portfolio() {
  const [cards, setCards] = useState<PortfolioCard[]>([])
  const [history, setHistory] = useState<HistoryPoint[]>([])
  const [loading, setLoading] = useState(() => !!getToken())
  const [error, setError] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('recent')
  const [nameFilter, setNameFilter] = useState('')
  const [plFilter, setPlFilter] = useState<PLFilter>('all')
  const [range, setRange] = useState<Range>('1M')
  // The right-edge marker on the value chart waits for the area's reveal
  // animation to finish (onAnimationEnd) so it doesn't sit there while the line
  // is still drawing; reset to false whenever the range toggle re-animates it.
  const [showChartDot, setShowChartDot] = useState(false)
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

  if (!getToken()) {
    return <SignedOutHero variant="portfolio" />
  }

  if (loading) return <PageMessage><p>Loading portfolio...</p></PageMessage>
  if (error) return <PageMessage><p className="error">{error}</p></PageMessage>

  // ----- Portfolio-wide figures (always the full portfolio, not the filtered view)
  const totalValue = cards.reduce((sum, c) => sum + (c.current_price ?? c.purchase_price) * c.quantity, 0)
  const totalCost = cards.reduce((sum, c) => sum + c.purchase_price * c.quantity, 0)
  const totalGainLoss = cards.reduce((sum, c) => sum + (c.gain_loss ?? 0), 0)
  const allTimePct = totalCost > 0 ? Math.round((totalGainLoss / totalCost) * 10000) / 100 : null
  const lotCount = cards.length

  const groups = groupByCard(cards)
  const metrics = new Map(groups.map(g => [g.card_id, groupMetrics(g)]))

  // Today's total move (per-unit day change × quantity, summed) and the best %
  // mover across the portfolio — the two right-hand hero stat cells.
  let today = 0
  let hasToday = false
  let bestMover: number | null = null
  for (const g of groups) {
    const dc = metrics.get(g.card_id)!.dayChange
    if (dc != null) { today += dc; hasToday = true }
    const pct = g.price_change?.percent
    if (pct != null && (bestMover == null || pct > bestMover)) bestMover = pct
  }

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

  // ----- Value-over-time chart, scoped to the selected range ---------------------
  const days = RANGE_DAYS[range]
  let chartData = history
  if (days != null && history.length) {
    // Anchor the window to the latest snapshot (≈ today) rather than a live clock
    // read, which the purity lint forbids during render.
    const anchor = new Date(history[history.length - 1].date + 'T00:00:00')
    anchor.setDate(anchor.getDate() - days)
    const cutoff = localISODate(anchor)
    const filtered = history.filter(p => p.date >= cutoff)
    if (filtered.length >= 2) chartData = filtered
  }
  // With under two days of history in range, show a flat line at the current value
  const isPlaceholder = chartData.length < 2
  if (isPlaceholder) {
    const now = new Date()
    const yesterday = new Date(now)
    yesterday.setDate(now.getDate() - 1)
    chartData = [
      { date: localISODate(yesterday), total_value: totalValue },
      { date: localISODate(now), total_value: totalValue },
    ]
  }
  const lastPoint = chartData[chartData.length - 1]
  const [dollars, cents] = money(totalValue).split('.')
  const gainDir = totalGainLoss > 0 ? 'positive' : totalGainLoss < 0 ? 'negative' : 'flat'

  if (cards.length === 0) {
    return (
      <div className="page">
        <h1>My Portfolio</h1>
        <div className="centered">
          <p>No cards yet.</p>
          <Link to="/search" className="btn-primary" style={{ marginTop: '16px' }}>Search Cards</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <h1 className={styles.srOnly}>My Portfolio</h1>

      {/* ---- Hero panel: value + all-time change + stat grid (left), chart (right) */}
      <section className={styles.hero}>
        <div className={styles.heroLeft}>
          <div>
            <span className={styles.heroLabel}>Portfolio value</span>
            <div className={`${styles.heroValue} num`}>{dollars}<span className={styles.heroCents}>.{cents}</span></div>
            <div className={`${styles.changePill} ${styles[gainDir]} num`}>
              <span className={styles.changeArrow}>{totalGainLoss > 0 ? '▲' : totalGainLoss < 0 ? '▼' : '–'}</span>
              {money(Math.abs(totalGainLoss))}
              {allTimePct != null && (
                <span className={styles.changePct}> ({allTimePct > 0 ? '+' : allTimePct < 0 ? '−' : ''}{Math.abs(allTimePct)}%)</span>
              )}
            </div>
          </div>

          <div className={styles.statGrid}>
            <div className={styles.statCell}>
              <span className="stat-label">Cost basis</span>
              <span className={`${styles.statValue} num`}>{money(totalCost)}</span>
            </div>
            <div className={styles.statCell}>
              <span className="stat-label">Cards</span>
              <span className={`${styles.statValue} num`}>
                {groups.length}<span className={styles.statSub}> · {lotCount} {lotCount === 1 ? 'lot' : 'lots'}</span>
              </span>
            </div>
            <div className={styles.statCell}>
              <span className="stat-label">Today</span>
              <span className={`${styles.statValue} num ${hasToday ? (today >= 0 ? 'positive' : 'negative') : ''}`}>
                {hasToday ? signedMoney(today) : '—'}
              </span>
            </div>
            <div className={styles.statCell}>
              <span className="stat-label">Best mover</span>
              <span className={`${styles.statValue} num ${bestMover != null ? (bestMover >= 0 ? 'positive' : 'negative') : ''}`}>
                {bestMover != null ? `${bestMover > 0 ? '+' : bestMover < 0 ? '−' : ''}${Math.abs(bestMover).toFixed(1)}%` : '—'}
              </span>
            </div>
          </div>
        </div>

        <div className={styles.heroRight}>
          <div className={styles.heroChartHead}>
            <span className={styles.heroChartTitle}>Value over time</span>
            <div className="segmented on-card">
              {RANGES.map(r => (
                <button
                  key={r}
                  className={`segmented-item${range === r ? ' is-selected' : ''}`}
                  onClick={() => { setRange(r); setShowChartDot(false) }}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={210}>
            <AreaChart data={chartData} margin={{ top: 8, right: 6, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="portfolioFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.28} />
                  <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--hairline)" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={formatChartDate}
                stroke="var(--text)"
                fontSize={11.5}
                tickLine={false}
                axisLine={false}
                tickMargin={10}
                minTickGap={40}
              />
              <YAxis hide domain={['auto', 'auto']} />
              <Tooltip
                formatter={value => [money(Number(value)), 'Value']}
                labelFormatter={label => formatChartDate(String(label))}
                contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8 }}
                labelStyle={{ color: 'var(--text)' }}
              />
              <Area
                type="monotone"
                dataKey="total_value"
                stroke="var(--accent)"
                strokeWidth={2.5}
                fill="url(#portfolioFill)"
                onAnimationEnd={() => { if (!isPlaceholder) setShowChartDot(true) }}
              />
              {!isPlaceholder && showChartDot && (
                <ReferenceDot x={lastPoint.date} y={lastPoint.total_value} r={4.5} fill="var(--accent)" stroke="none" ifOverflow="extendDomain" />
              )}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* ---- Filter row: name, gainers/losers, sort, count -------------------- */}
      <div className={styles.filterRow}>
        <input
          value={nameFilter}
          onChange={e => setNameFilter(e.target.value)}
          placeholder="Filter by name"
          className={`filter-select ${styles.filterName}`}
        />
        <div className="segmented segmented-lg">
          {([['all', 'All'], ['gainers', 'Gainers'], ['losers', 'Losers']] as [PLFilter, string][]).map(([value, label]) => (
            <button
              key={value}
              className={`segmented-item${plFilter === value ? ' is-selected' : ''}`}
              onClick={() => setPlFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <select
          value={sortKey}
          onChange={e => setSortKey(e.target.value as SortKey)}
          className="filter-select"
        >
          {SORT_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <span className={`${styles.count} num`}>
          {isFiltered
            ? `${visibleGroups.length} of ${groups.length} cards`
            : `${groups.length} ${groups.length === 1 ? 'card' : 'cards'} · ${lotCount} ${lotCount === 1 ? 'lot' : 'lots'}`}
        </span>
      </div>

      {visibleGroups.length === 0 ? (
        <p className={styles.noMatch}>No cards match your filters.</p>
      ) : (
        <div className={styles.grid}>
          {visibleGroups.map(group => {
            const m = metrics.get(group.card_id)!
            const single = group.lots.length === 1
            return (
              <Link key={group.card_id} to={`/portfolio/${group.card_id}`} className={styles.tile}>
                <span className={styles.tileArt}>
                  <CardImage src={group.image_url ?? getCardImageUrl(group.card_id)} alt={group.card_name} />
                </span>
                <div>
                  <p className={styles.tileName}>{group.card_name}</p>
                  <p className={`${styles.tileMeta} num`}>Qty {m.qty}</p>
                </div>
                <div>
                  <div className={`${styles.tilePrice} num`}>{money(group.current_price)}</div>
                  {group.price_change && (
                    <DayChange change={group.price_change} today />
                  )}
                </div>
                <div className={`${styles.tileFooter} num`}>
                  <span>{single ? `paid ${money(m.avg)}` : `avg paid ${money(m.avg)}`}</span>
                  {m.gain != null && <GainLoss value={m.gain} />}
                </div>
              </Link>
            )
          })}

          <Link to="/search" className={styles.addTile}>
            <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
              <path d="M12 5v14M5 12h14" />
            </svg>
            <span>Add a card</span>
          </Link>
        </div>
      )}
    </div>
  )
}
