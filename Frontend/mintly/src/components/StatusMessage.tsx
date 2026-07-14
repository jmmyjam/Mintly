import type { ReactNode } from 'react'

// Success/error line shown after an add-to-portfolio attempt
export default function StatusMessage({ ok, children }: { ok: boolean; children: ReactNode }) {
  return <p className={ok ? 'success-msg' : 'error'}>{children}</p>
}
