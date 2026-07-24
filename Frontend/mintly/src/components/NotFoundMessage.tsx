import PageMessage from './PageMessage'

// The one 404 view, shared so it's byte-identical everywhere: the catch-all
// route renders it for unknown URLs, and Admin renders it for logged-out,
// expired-session, and non-admin visitors — a guessed /admin must be
// indistinguishable from a page that doesn't exist.
export default function NotFoundMessage() {
  return (
    <PageMessage action={{ to: '/', label: 'Back to home', className: 'btn-primary btn-lg' }}>
      <h2>Page not found</h2>
      <p>There's nothing at this address.</p>
    </PageMessage>
  )
}
