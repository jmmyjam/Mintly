import type { PriceChange } from '../api'

// Compact daily price-change chip shown beside a current market price
// (search tiles, card detail, portfolio) — so you can see the move without
// opening or adding the card. Green up / red down / muted when flat. `today`
// appends the word after the figure (portfolio grid tile + holding panel).
export default function DayChange({ change, className, today = false }: { change: PriceChange; className?: string; today?: boolean }) {
  const dir = change.amount > 0 ? 'positive' : change.amount < 0 ? 'negative' : 'flat'
  const arrow = change.amount > 0 ? '▲' : change.amount < 0 ? '▼' : '–'
  const sign = change.amount > 0 ? '+' : ''
  const since = new Date(change.since + 'T00:00:00').toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  })
  return (
    <span
      className={`day-change day-change-${dir} num${className ? ` ${className}` : ''}`}
      title={`Change since ${since}`}
    >
      <span className="day-change-arrow">{arrow}</span>
      {sign}${Math.abs(change.amount).toFixed(2)}
      {change.percent != null && (
        <span className="day-change-pct"> ({sign}{change.percent}%)</span>
      )}
      {today && ' today'}
    </span>
  )
}
