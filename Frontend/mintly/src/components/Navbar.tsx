import { useEffect, useState } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { clearToken, getToken } from '../api'

export default function Navbar() {
  const navigate = useNavigate()
  const location = useLocation()
  const loggedIn = !!getToken()
  // Auto-hide: slide away on scroll down, return on scroll up
  const [hidden, setHidden] = useState(false)

  useEffect(() => {
    let lastY = window.scrollY
    function onScroll() {
      const y = window.scrollY
      setHidden(y > lastY && y > 80)
      lastY = y
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  function handleLogout() {
    clearToken()
    navigate('/')
  }

  return (
    <nav className={hidden ? 'navbar navbar-hidden' : 'navbar'}>
      <Link to="/" className="navbar-brand">
        <img src="/favicon.svg" alt="" className="brand-logo" />
        Mintly
      </Link>
      <div className="nav-pill">
        <Link to="/search" className={location.pathname === '/search' ? 'nav-link active' : 'nav-link'}>
          Search
        </Link>
        <Link to="/portfolio" className={location.pathname === '/portfolio' ? 'nav-link active' : 'nav-link'}>
          Portfolio
        </Link>
      </div>
      <div className="navbar-right">
        {loggedIn ? (
          <button onClick={handleLogout} className="btn-outline">Logout</button>
        ) : (
          <Link to="/login" className="btn-outline">Login</Link>
        )}
      </div>
    </nav>
  )
}
