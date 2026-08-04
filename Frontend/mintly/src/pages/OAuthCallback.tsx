import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { setToken } from '../api'
import { clearPortfolios } from '../portfolios'
import { invalidateOwned } from '../owned'
import PageMessage from '../components/PageMessage'

// Where the backend sends the browser after a successful social sign-in. The
// JWT arrives in the URL fragment (never sent to a server, kept out of logs and
// Referer). We store it, scrub it from the address bar, and land on the
// portfolio — mirroring the password login flow. A missing token means the
// redirect was malformed, so bounce to /login with a notice.
export default function OAuthCallback() {
  const navigate = useNavigate()

  useEffect(() => {
    const match = window.location.hash.match(/token=([^&]+)/)
    if (match) {
      setToken(decodeURIComponent(match[1]))
      // Fresh sign-in: drop any cached data from a previous account so the new
      // one's portfolios/owned badges load clean (same as a logout would).
      clearPortfolios()
      invalidateOwned()
      // Replace the current history entry so the token fragment leaves no trace.
      navigate('/portfolio', { replace: true })
    } else {
      navigate('/login', {
        replace: true,
        state: { notice: "We couldn't complete sign-in. Please try again." },
      })
    }
  }, [navigate])

  return (
    <PageMessage>
      <p>Signing you in...</p>
    </PageMessage>
  )
}
