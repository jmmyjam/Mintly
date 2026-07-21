import { useEffect, useState } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { clearToken, getToken } from '../api'
import styles from './Navbar.module.css'

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
    navigate('/login', { state: { notice: "You've been logged out successfully." } })
  }

  return (
    <nav className={hidden ? `${styles.navbar} ${styles.navbarHidden}` : styles.navbar}>
      <Link to="/" className={styles.navbarBrand}>
        <img src="/favicon.svg" alt="" className={styles.brandLogo} />
        <span className={styles.brandText}>Mintly</span>
      </Link>
      <div className={styles.navPill}>
        <Link to="/search" className={location.pathname === '/search' ? `${styles.navLink} ${styles.active}` : styles.navLink}>
          Search
        </Link>
        <Link to="/portfolio" className={location.pathname === '/portfolio' ? `${styles.navLink} ${styles.active}` : styles.navLink}>
          Portfolio
        </Link>
      </div>
      <div className={styles.navbarRight}>
        {loggedIn ? (
          <button onClick={handleLogout} className="btn-outline">Logout</button>
        ) : (
          <Link to="/login" className="btn-outline">Login</Link>
        )}
      </div>
    </nav>
  )
}
