import { useEffect, useMemo, useState } from 'react'
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ReferenceDot, ResponsiveContainer,
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

// A single purchase to mark on the chart (holding route): a cream-ringed dot at
// (date, price paid). Snapped to the nearest tracked day so it lands on a category.
export interface PurchaseMarker {
  date: string // YYYY-MM-DD (local calendar day)
  price: number
}

// Per-card price tracker over Mintly's own snapshots, which build up over time,
// so early on it may be sparse. Single-variant cards render the headline series
// as an area; cards with 2+ tracked variants render one colored line per
// variant (fixed color per variant name, legend + line-end labels carrying
// identity alongside color). `currentPrice`/`currentVariantPrices` are the live
// numbers shown above/below the chart — each series ends on its own.
//
// The holding route (/portfolio/:cardId) passes `title`, a `segmentedRange`
// toggle, and cost overlays — `avgCost` (a dashed reference line + a right-edge
// pill) and `purchases` (cream-ringed dots) — that layer on top of either mode.
export default function PriceHistoryChart({
  cardId, currentPrice, currentVariantPrices, onData,
  title = 'Price History', segmentedRange = false, avgCost, purchases,
}: {
  cardId: string
  currentPrice?: number | null
  currentVariantPrices?: { [variant: string]: number }
  onData?: (history: CardHistory) => void
  title?: string
  segmentedRange?: boolean
  avgCost?: number | null
  purchases?: PurchaseMarker[]
}) {
  const [history, setHistory] = useState<CardHistory | null>(null)
  const [loading, setLoading] = useState(true)
  const [range, setRange] = useState(segmentedRange ? '1m' : 'all')

  // The cost overlays (holding route) only render when there's a position to
  // draw; when present they also give the panel the larger holding-page radius.
  const hasOverlays = avgCost != null || (purchases?.length ?? 0) > 0
  const panelClass = `${styles.priceHistory}${hasOverlays ? ` ${styles.withOverlays}` : ''}`

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
      <div className={panelClass}>
        <h2>{title}</h2>
        <p className="prices-note">Loading price history…</p>
      </div>
    )
  }

  // With a single point (or none), there's no line to draw yet — the snapshot
  // store only grows as the card is viewed over time.
  if (allRows.length < 2) {
    return (
      <div className={panelClass}>
        <h2>{title}</h2>
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

  // Snap each purchase to the nearest tracked day within the visible window, so
  // its marker sits on the market line; purchases outside the window are dropped.
  const catDates = chartData.map(r => (r as { date: string }).date)
  const markers = purchases && catDates.length
    ? purchases.flatMap(p => {
        if (p.date < catDates[0] || p.date > catDates[catDates.length - 1]) return []
        let best = catDates[0]
        let bestDiff = Infinity
        for (const d of catDates) {
          const diff = Math.abs(Date.parse(d) - Date.parse(p.date))
          if (diff < bestDiff) { bestDiff = diff; best = d }
        }
        return [{ x: best, price: p.price }]
      })
    : []

  // A cost pill anchored at the right end of the avg-cost reference line —
  // recharts hands us the line's plotted viewBox so it tracks the real y.
  const avgLabel = ({ viewBox }: { viewBox?: { x?: number; y?: number; width?: number } }) => {
    if (!viewBox || viewBox.x == null || viewBox.y == null || viewBox.width == null || avgCost == null) return <g />
    const text = `your avg ${money(avgCost)}`
    const h = 20
    const w = text.length * 6.4 + 16
    const x = viewBox.x + viewBox.width - w - 2
    const y = viewBox.y - h / 2
    return (
      <g>
        <rect x={x} y={y} width={w} height={h} rx={h / 2} fill="var(--bg)" stroke="rgba(224,112,92,.4)" />
        <text x={x + w / 2} y={viewBox.y + 4} textAnchor="middle" fill="var(--negative)" fontSize={11.5} style={{ fontVariantNumeric: 'tabular-nums' }}>{text}</text>
      </g>
    )
  }

  const overlays = hasOverlays ? (
    <>
      {avgCost != null && (
        <ReferenceLine y={avgCost} stroke="var(--negative)" strokeDasharray="5 5" strokeWidth={1.5} ifOverflow="extendDomain" label={avgLabel} />
      )}
      {markers.map((m, i) => (
        <ReferenceDot key={`pm-${i}`} x={m.x} y={m.price} r={5} fill="var(--bg)" stroke="var(--cream)" strokeWidth={2} ifOverflow="extendDomain" />
      ))}
    </>
  ) : null

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
    <div className={panelClass}>
      <div className={styles.priceHistoryHead}>
        <h2>{title}</h2>
        {segmentedRange ? (
          <div className="segmented on-card">
            {RANGES.map(r => (
              <button
                key={r.key}
                className={`segmented-item${range === r.key ? ' is-selected' : ''}`}
                onClick={() => setRange(r.key)}
              >
                {r.label}
              </button>
            ))}
          </div>
        ) : (
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
        )}
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
            {overlays}
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
            {overlays}
          </AreaChart>
        )}
      </ResponsiveContainer>
      {hasOverlays && (
        <div className={styles.costLegend}>
          {!multi && (
            <span className={styles.costLegendItem}>
              <span className={styles.swatchLine} />Market price
            </span>
          )}
          {markers.length > 0 && (
            <span className={styles.costLegendItem}>
              <span className={styles.swatchDot} />Your purchases
            </span>
          )}
          {avgCost != null && (
            <span className={styles.costLegendItem}>
              <span className={styles.swatchDash} />Your average cost
            </span>
          )}
        </div>
      )}
    </div>
  )
}
