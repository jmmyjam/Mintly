import NotFoundMessage from '../components/NotFoundMessage'

// Catch-all route (path="*") — any URL no other route matches, e.g. /taco
export default function NotFound() {
  return <NotFoundMessage />
}
