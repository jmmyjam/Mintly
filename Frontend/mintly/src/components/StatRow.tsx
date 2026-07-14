import type { ReactNode } from 'react'

// A label/value line — card facts on the detail page, price breakdowns in the portfolio
export default function StatRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="price-row">
      <span className="stat-label">{label}</span>
      <span>{children}</span>
    </div>
  )
}
