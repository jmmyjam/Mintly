import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { getToken } from '../api'
import { useAccessibility } from '../accessibility'
import styles from './Navbar.module.css'

export default function Navbar() {
  const location = useLocation()
  const loggedIn = !!getToken()
  const { settings } = useAccessibility()
  // Auto-hide: slide away on scroll down, return on scroll up
  const [hidden, setHidden] = useState(false)

  useEffect(() => {
    // Reduce-motion users keep the bar pinned — no sliding chrome
    if (settings.reduceMotion) return
    let lastY = window.scrollY
    function onScroll() {
      const y = window.scrollY
      setHidden(y > lastY && y > 80)
      lastY = y
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [settings.reduceMotion])

  const isHidden = hidden && !settings.reduceMotion

  return (
    <nav className={isHidden ? `${styles.navbar} ${styles.navbarHidden}` : styles.navbar}>
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
          <Link
            to="/profile"
            aria-label="Profile"
            className={location.pathname === '/profile' ? `${styles.avatar} ${styles.avatarActive}` : styles.avatar}
          >
            {/* Generic profile silhouette — no avatar upload in the app yet */}
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor"
                 strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="9" r="3.2" />
              <path d="M5.5 19.2a6.5 6.5 0 0 1 13 0" />
            </svg>
          </Link>
        ) : (
          <Link to="/login" className="btn-outline">Login</Link>
        )}
      </div>
    </nav>
  )
}
