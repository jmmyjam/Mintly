import { Link } from 'react-router-dom'
import styles from './Footer.module.css'

export default function Footer() {
  return (
    <footer className={styles.footer}>
      <div className={styles.footerInner}>
        <div className={styles.footerTop}>
          <Link to="/" className={styles.footerBrand}>
            <img src="/favicon.svg" alt="" />
            Mintly
          </Link>
          <nav className={styles.footerLinks}>
            <Link to="/search">Search</Link>
            <Link to="/portfolio">Portfolio</Link>
            <Link to="/terms">Terms</Link>
            <Link to="/privacy">Privacy</Link>
          </nav>
        </div>
        <p className={styles.footerDisclaimer}>
          Mintly is an unofficial fan project and is not affiliated with,
          endorsed, or sponsored by Nintendo, The Pokémon Company, TCGplayer,
          or eBay. Pokémon names and card images are trademarks and copyrights
          of their respective owners. Card data is provided by the Pokémon TCG
          API, with some estimates drawn from recent eBay sold listings; all
          prices are informational estimates only and do not constitute
          financial advice.
        </p>
        <div className={styles.footerBottom}>
          <span>© {new Date().getFullYear()} Mintly. All rights reserved.</span>
          <span>Made for collectors.</span>
        </div>
      </div>
    </footer>
  )
}
