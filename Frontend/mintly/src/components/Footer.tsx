import { Link } from 'react-router-dom'

export default function Footer() {
  return (
    <footer className="footer">
      <div className="footer-inner">
        <div className="footer-top">
          <Link to="/" className="footer-brand">
            <img src="/favicon.svg" alt="" />
            Mintly
          </Link>
          <nav className="footer-links">
            <Link to="/search">Search</Link>
            <Link to="/portfolio">Portfolio</Link>
            <Link to="/terms">Terms</Link>
            <Link to="/privacy">Privacy</Link>
          </nav>
        </div>
        <p className="footer-disclaimer">
          Mintly is an unofficial fan project and is not affiliated with,
          endorsed, or sponsored by Nintendo, The Pokémon Company, TCGplayer,
          or eBay. Pokémon names and card images are trademarks and copyrights
          of their respective owners. Card data is provided by the Pokémon TCG
          API, with some estimates drawn from recent eBay sold listings; all
          prices are informational estimates only and do not constitute
          financial advice.
        </p>
        <div className="footer-bottom">
          <span>© {new Date().getFullYear()} Mintly. All rights reserved.</span>
          <span>Made for collectors.</span>
        </div>
      </div>
    </footer>
  )
}
