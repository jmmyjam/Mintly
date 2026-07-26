import { useEffect, useMemo, useState } from 'react'
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { getCardHistory, type CardHistory, type PricePoint } from '../api'
import { money } from '../format'
import { mergeHeadline, sortVariants, variantColor, variantLabel, variantShortLabel } from '../variants'
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

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

// Pin a series' newest point to the live price shown elsewhere on the page, so
// the chart never contradicts it (the stored snapshot can lag a background
// price refresh). Older points are historical fact and left untouched.
function overlayCurrent(points: PricePoint[], current: number | null | undefined): PricePoint[] {
  if (current == null || points.length === 0) return points
  const today = todayIso()
  if (points[points.length - 1].date >= today) {
    const copy = points.slice()
    copy[copy.length - 1] = { ...copy[copy.length - 1], price: current }
    return copy
  }
  return [...points, { date: today, price: current }]
}

// Per-card price tracker over Mintly's own snapshots, which build up over time,
// so early on it may be sparse. Single-variant cards render the headline series
// as an area; cards with 2+ tracked variants render one colored line per
// variant (fixed color per variant name, legend + line-end labels carrying
// identity alongside color). `currentPrice`/`currentVariantPrices` are the live
// numbers shown above/below the chart — each series ends on its own.
export default function PriceHistoryChart({ cardId, currentPrice, currentVariantPrices, onData }: {
  cardId: string
  currentPrice?: number | null
  currentVariantPrices?: { [variant: string]: number }
  onData?: (history: CardHistory) => void
}) {
  const [history, setHistory] = useState<CardHistory | null>(null)
  const [loading, setLoading] = useState(true)
  const [range, setRange] = useState('all')

  // Remounted per card (keyed by cardId at the call site), so loading starts
  // true and this effect runs once — no synchronous setState in the body.
  useEffect(() => {
    let cancelled = false
    getCardHistory(cardId)
      .then(data => {
        if (!cancelled) {
          setHistory(data)
          onData?.(data)
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [cardId, onData])

  const variantKeys = useMemo(
    () => sortVariants(Object.keys(history?.variants ?? {})),
    [history],
  )
  const multi = variantKeys.length >= 2

  // Headline series (single-variant mode), ending on the live price
  const series = useMemo(
    () => overlayCurrent(history?.points ?? [], currentPrice),
    [history, currentPrice],
  )

  // Variant series merged into one row per date for the multi-line chart
  const variantRows = useMemo(() => {
    if (!history || !multi) return []
    const merged = mergeHeadline(history.points, history.variants)
    const byDate = new Map<string, { date: string; [variant: string]: string | number }>()
    for (const key of variantKeys) {
      for (const p of overlayCurrent(merged[key], currentVariantPrices?.[key])) {
        const row = byDate.get(p.date) ?? { date: p.date }
        row[key] = p.price
        byDate.set(p.date, row)
      }
    }
    return [...byDate.values()].sort((a, b) => (a.date < b.date ? -1 : 1))
  }, [history, multi, variantKeys, currentVariantPrices])

  const days = RANGES.find(r => r.key === range)!.days
  const cutoffIso = useMemo(() => {
    if (days == null) return null
    const cutoff = new Date()
    cutoff.setDate(cutoff.getDate() - days)
    return cutoff.toISOString().slice(0, 10)
  }, [days])

  const allRows = multi ? variantRows : series
  const visible = cutoffIso == null ? allRows : allRows.filter(p => p.date >= cutoffIso)
  const chartData = cutoffIso == null || visible.length >= 2 ? visible : allRows

  // Where each variant's line ends in the visible window — its direct label
  // (short variant name) renders there, so identity never rides on color alone.
  // pointCount backs the one-point case: a just-started series has no line to
  // draw, so it gets a dot instead of an invisible label anchor.
  const lastIndex: { [variant: string]: number } = {}
  const pointCount: { [variant: string]: number } = {}
  if (multi) {
    chartData.forEach((row, i) => {
      for (const key of variantKeys) {
        if ((row as { [k: string]: unknown })[key] != null) {
          lastIndex[key] = i
          pointCount[key] = (pointCount[key] ?? 0) + 1
        }
      }
    })
  }

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
  if (allRows.length < 2) {
    return (
      <div className={styles.priceHistory}>
        <h2>Price History</h2>
        <p className="prices-note">
          Not enough history yet. Mintly records one price point per day, so this
          chart fills in as the card is tracked.
        </p>
      </div>
    )
  }

  const endLabel = (variant: string) =>
    (props: { x?: number | string; y?: number | string; index?: number }) => {
      if (props.index !== lastIndex[variant] || props.x == null || props.y == null) return <g />
      return (
        <text x={Number(props.x) + 7} y={Number(props.y) + 4} fill="var(--text)" fontSize={11}>
          {variantShortLabel(variant)}
        </text>
      )
    }

  const axes = (
    <>
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
    </>
  )

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
      {multi && (
        <div className={styles.legend}>
          {variantKeys.map(key => (
            <span key={key} className={styles.legendItem}>
              <span className={styles.legendSwatch} style={{ background: variantColor(key) }} />
              {variantLabel(key)}
            </span>
          ))}
        </div>
      )}
      <ResponsiveContainer width="100%" height={260}>
        {multi ? (
          <LineChart data={chartData} margin={{ top: 8, right: 76, left: 0, bottom: 0 }}>
            {axes}
            <Tooltip
              formatter={(value, name) => [money(Number(value)), String(name)]}
              labelFormatter={label => formatDate(String(label))}
              contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8 }}
              labelStyle={{ color: 'var(--text)' }}
              itemStyle={{ color: 'var(--text)' }}
            />
            {variantKeys.map(key => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                name={variantLabel(key)}
                stroke={variantColor(key)}
                strokeWidth={2}
                dot={pointCount[key] === 1 ? { r: 3, strokeWidth: 0, fill: variantColor(key) } : false}
                activeDot={{ r: 4 }}
                connectNulls
                isAnimationActive={false}
                label={endLabel(key)}
              />
            ))}
          </LineChart>
        ) : (
          <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="historyFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.3} />
                <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
              </linearGradient>
            </defs>
            {axes}
            <Tooltip
              formatter={value => [money(Number(value)), 'Price']}
              labelFormatter={label => formatDate(String(label))}
              contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8 }}
              labelStyle={{ color: 'var(--text)' }}
            />
            <Area type="monotone" dataKey="price" stroke="var(--accent)" strokeWidth={2} fill="url(#historyFill)" />
          </AreaChart>
        )}
      </ResponsiveContainer>
    </div>
  )
}
