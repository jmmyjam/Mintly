import styles from './SetCompletionMeter.module.css'

interface Props {
  owned: number
  total: number
  // Accessible name for the progressbar (e.g. "45 of 102 cards owned in Base").
  // Falls back to a generic count when omitted.
  label?: string
  // Append a muted "· 44%" after the count (used in the Portfolio rollup rows).
  showPercent?: boolean
  className?: string
}

// A labeled completion bar: how many of a set's cards you own vs its total. The
// numeric "owned/total" is real text (never color-alone), the bar is a
// progressbar with aria-value*, and the mint fill sits on a recessive track.
export default function SetCompletionMeter({ owned, total, label, showPercent, className }: Props) {
  const pct = total > 0 ? Math.min(100, Math.round((owned / total) * 100)) : 0
  const complete = total > 0 && owned >= total
  return (
    <div className={`${styles.meter}${className ? ` ${className}` : ''}`}>
      <div
        className={styles.track}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={owned}
        aria-label={label ?? `${owned} of ${total} cards owned`}
      >
        <div
          className={`${styles.fill}${complete ? ` ${styles.complete}` : ''}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={styles.count}>
        <span className="num">{owned}</span>
        <span className={styles.slash}>/</span>
        <span className="num">{total}</span>
        {showPercent && <span className={styles.pct}> · {pct}%</span>}
      </span>
    </div>
  )
}
