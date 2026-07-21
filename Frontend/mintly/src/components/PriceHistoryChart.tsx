import { useEffect, useMemo, useState } from 'react'
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { getCardHistory, type PricePoint } from '../api'
import { money } from '../format'
import styles from './PriceHistoryChart.module.css'

// Ranges the user can scope the history to; "All" spans the full ~5-year window
const RANGES: { key: string; label: string; days: number | null }[] = [
  { key: '1m', label: '1M', days: 30 },
  { key: '6m', label: '6M', days: 180 },
  { key: '1y', label: '1Y', days: 365 },
  { key: 'all', label: 'All', days: null },
]

function formatDate(d: string) {
  return new Date(d + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' })
}

// Per-card price tracker: a single series (this card's daily market price) so no
// legend is needed — the heading names it. Data is Mintly's own snapshots, which
// build up over time, so early on it may be sparse. `currentPrice` is the live
// price shown at the top of the page — the chart ends on it so the graph never
// contradicts the number above it (see the reconciliation below).
export default function PriceHistoryChart({ cardId, currentPrice }: { cardId: string; currentPrice?: number | null }) {
  const [points, setPoints] = useState<PricePoint[]>([])
  const [loading, setLoading] = useState(true)
  const [range, setRange] = useState('all')

  // Remounted per card (keyed by cardId at the call site), so loading starts
  // true and this effect runs once — no synchronous setState in the body.
  useEffect(() => {
    let cancelled = false
    getCardHistory(cardId)
      .then(data => {
        if (!cancelled) setPoints(data)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [cardId])

  // The stored snapshot can lag the live price (a >6h-old catalog price refreshes
  // in the background, possibly after this chart already loaded), so overlay the
  // current price onto today's point — the line always ends where the big price
  // does. Older points are historical fact and left untouched.
  const series = useMemo(() => {
    if (currentPrice == null || points.length === 0) return points
    const today = new Date().toISOString().slice(0, 10)
    if (points[points.length - 1].date >= today) {
      const copy = points.slice()
      copy[copy.length - 1] = { ...copy[copy.length - 1], price: currentPrice }
      return copy
    }
    return [...points, { date: today, price: currentPrice }]
  }, [points, currentPrice])

  const days = RANGES.find(r => r.key === range)!.days
  const visible = useMemo(() => {
    if (days == null) return series
    const cutoff = new Date()
    cutoff.setDate(cutoff.getDate() - days)
    const iso = cutoff.toISOString().slice(0, 10)
    return series.filter(p => p.date >= iso)
  }, [series, days])

  if (loading) {
    return (
      <div className={styles.priceHistory}>
        <h2>Price History</h2>
        <p className="prices-note">Loading price history…</p>
      </div>
    )
  }

  // With a single point (or none), there's no line to draw yet — the snapshot
  // store only grows as the card is viewed over time.
  if (series.length < 2) {
    return (
      <div className={styles.priceHistory}>
        <h2>Price History</h2>
        <p className="prices-note">
          Not enough history yet — Mintly records one price point per day, so this
          chart fills in as the card is tracked.
        </p>
      </div>
    )
  }

  const chartData = days == null || visible.length >= 2 ? visible : series

  return (
    <div className={styles.priceHistory}>
      <div className={styles.priceHistoryHead}>
        <h2>Price History</h2>
        <div className={styles.rangeToggle}>
          {RANGES.map(r => (
            <button
              key={r.key}
              className={`${styles.rangeBtn}${range === r.key ? ' ' + styles.active : ''}`}
              onClick={() => setRange(r.key)}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="historyFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.3} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={formatDate}
            stroke="var(--text)"
            fontSize={12}
            tickLine={false}
            axisLine={false}
            minTickGap={32}
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
            formatter={value => [money(Number(value)), 'Price']}
            labelFormatter={label => formatDate(String(label))}
            contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8 }}
            labelStyle={{ color: 'var(--text)' }}
          />
          <Area type="monotone" dataKey="price" stroke="var(--accent)" strokeWidth={2} fill="url(#historyFill)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
