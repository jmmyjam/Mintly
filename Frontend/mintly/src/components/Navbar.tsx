import { Link, useNavigate, useLocation } from 'react-router-dom'
import { clearToken, getToken } from '../api'

export default function Navbar() {
  const navigate = useNavigate()
  const location = useLocation()
  const loggedIn = !!getToken()

  function handleLogout() {
    clearToken()
    navigate('/')
  }

  return (
    <nav className="navbar">
      <Link to="/" className="navbar-brand">Mintly</Link>
      <div className="navbar-links">
        <Link to="/search" className={location.pathname === '/search' ? 'nav-link active' : 'nav-link'}>
          Search
        </Link>
        <Link to="/portfolio" className={location.pathname === '/portfolio' ? 'nav-link active' : 'nav-link'}>
          Portfolio
        </Link>
        {loggedIn ? (
          <button onClick={handleLogout} className="btn-outline">Logout</button>
        ) : (
          <Link to="/login" className="btn-primary">Login</Link>
        )}
      </div>
    </nav>
  )
}
