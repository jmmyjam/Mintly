import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { addCard, errorMessage, getToken, SessionExpiredError, type LotCondition } from './api'
import { invalidateOwned } from './owned'
import { invalidateSetCompletion } from './setCompletion'

// The one notice Login.tsx displays when an authed call 401s — every redirect must
// use this exact flow, so new authed features should reuse this hook.
export function useSessionRedirect() {
  const navigate = useNavigate()
  return () =>
    navigate('/login', { state: { notice: 'Your session expired. Please log in again.' } })
}

export interface AddCardStatus {
  id: string
  msg: string
  ok: boolean
}

// Add-to-portfolio flow shared by Search and CardDetail: token check, price/qty
// parsing, and a status message that clears itself (3s on success, 4s on error).
export function useAddCard() {
  const navigate = useNavigate()
  const redirectToLogin = useSessionRedirect()
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<AddCardStatus | null>(null)

  async function add(cardId: string, priceInput: string, qtyInput: string, portfolioId?: number | null, onSuccess?: () => void, condition?: LotCondition | null) {
    if (!getToken()) {
      navigate('/login')
      return
    }
    if (busy) return
    setBusy(true)
    try {
      const price = parseFloat(priceInput)
      const msg = await addCard(cardId, Number.isNaN(price) ? null : price, parseInt(qtyInput) || 1, portfolioId, condition)
      // The portfolio changed — drop the owned-qty + set-completion caches so
      // Search re-badges and the completion meters refresh
      invalidateOwned()
      invalidateSetCompletion()
      onSuccess?.()
      setStatus({ id: cardId, msg, ok: true })
      setTimeout(() => setStatus(null), 3000)
    } catch (err: unknown) {
      if (err instanceof SessionExpiredError) {
        redirectToLogin()
        return
      }
      const msg = errorMessage(err, "We couldn't add that card. Please try again.")
      setStatus({ id: cardId, msg, ok: false })
      setTimeout(() => setStatus(null), 4000)
    } finally {
      setBusy(false)
    }
  }

  return { add, busy, status }
}
