import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

// Full-page centered state (loading / error / logged-out) with an optional CTA link
interface PageMessageProps {
  children: ReactNode
  action?: { to: string; label: string; className?: string }
}

export default function PageMessage({ children, action }: PageMessageProps) {
  return (
    <div className="page centered">
      {children}
      {action && (
        <Link to={action.to} className={action.className ?? 'btn-primary'} style={{ marginTop: '16px' }}>
          {action.label}
        </Link>
      )}
    </div>
  )
}
