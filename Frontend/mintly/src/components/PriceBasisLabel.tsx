import type { PriceBasis } from '../portfolio'
import styles from './PriceBasisLabel.module.css'

// Says where a holding's figure came from, so a scraped slab median is never
// mistaken for a market quote. Mirrors the muted "eBay est." label the Search
// grid puts on TCGplayer-priceless cards — a graded lot is the same kind of
// claim (a median over recent sold comps), and reads the same way here.
//
// `detail` adds the comp count / the at-cost explanation. Tiles stay terse; the
// Holding page, where someone is actually studying the position, gets it.
interface PriceBasisLabelProps {
  basis: PriceBasis
  detail?: boolean
}

export default function PriceBasisLabel({ basis, detail = false }: PriceBasisLabelProps) {
  // The normal TCGplayer path is the unlabelled default everywhere else in the
  // app; labelling it here would only add noise.
  if (basis.kind === 'market') return null

  if (basis.kind === 'cost') {
    return (
      <span className={styles.atCost}>
        {detail
          ? 'At cost. No recent graded sales to price this from.'
          : 'at cost'}
      </span>
    )
  }

  return (
    <span className={styles.est}>
      eBay est.
      {detail && basis.sales > 0 &&
        ` from ${basis.sales} recent sale${basis.sales === 1 ? '' : 's'}`}
    </span>
  )
}
