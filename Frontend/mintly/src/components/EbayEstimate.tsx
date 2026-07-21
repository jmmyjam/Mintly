import type { EbayEstimate as Estimate } from '../api'
import { money } from '../format'
import StatRow from './StatRow'
import styles from './EbayEstimate.module.css'

function formatDate(d: string) {
  return new Date(d + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// Recent eBay sold-listing estimate, shown for cards the TCGPlayer feed can't
// price. Presentational — the page fetches the estimate and owns the state.
export default function EbayEstimate({ estimate }: { estimate: Estimate }) {
  if (estimate.count === 0) {
    return (
      <div className={styles.ebayEstimate}>
        <h2>Recent eBay Sales</h2>
        <p className="prices-note">
          No recent eBay sales found for this card.{' '}
          <a href={estimate.source_url} target="_blank" rel="noopener noreferrer">
            Search eBay
          </a>
        </p>
      </div>
    )
  }

  return (
    <div className={styles.ebayEstimate}>
      <h2>Recent eBay Sales</h2>
      <p className={styles.ebayHeadline}>
        <span className={styles.ebayMedian}>{money(estimate.median)}</span>
        <span className={styles.ebayMedianLabel}>median of {estimate.count} recent sales</span>
      </p>
      <div className="price-rows">
        <StatRow label="Average">{money(estimate.average)}</StatRow>
        <StatRow label="Range">{money(estimate.low)} – {money(estimate.high)}</StatRow>
        {estimate.since && estimate.until && (
          <StatRow label="Sold">
            {estimate.since === estimate.until
              ? formatDate(estimate.until)
              : `${formatDate(estimate.since)} – ${formatDate(estimate.until)}`}
          </StatRow>
        )}
      </div>
      <p className="prices-note">
        Estimated from recent sold listings on eBay (graded and lot listings excluded).{' '}
        <a href={estimate.source_url} target="_blank" rel="noopener noreferrer">
          View on eBay
        </a>
      </p>
    </div>
  )
}
