// Signed dollar amount colored by direction, with an optional percent suffix
interface GainLossProps {
  value: number
  pct?: number | null
  className?: string
}

export default function GainLoss({ value, pct, className }: GainLossProps) {
  return (
    <span className={`${value >= 0 ? 'positive' : 'negative'}${className ? ` ${className}` : ''}`}>
      {value >= 0 ? '+' : ''}${value.toFixed(2)}
      {pct != null && (
        <span className="pct"> ({pct > 0 ? '+' : ''}{pct}%)</span>
      )}
    </span>
  )
}
