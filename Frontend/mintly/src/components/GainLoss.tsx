import { signedMoney } from '../format'

// Signed dollar amount colored by direction, with an optional percent suffix
interface GainLossProps {
  value: number
  pct?: number | null
  className?: string
}

export default function GainLoss({ value, pct, className }: GainLossProps) {
  return (
    <span className={`${value >= 0 ? 'positive' : 'negative'} num${className ? ` ${className}` : ''}`}>
      {signedMoney(value)}
      {pct != null && (
        <span className="pct"> ({pct > 0 ? '+' : ''}{pct}%)</span>
      )}
    </span>
  )
}
