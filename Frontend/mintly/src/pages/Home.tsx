import { Link } from 'react-router-dom'

export default function Home() {
  return (
    <div className="home">
      <div className="home-hero">
        <h1 className="home-title">Track Your Pokemon TCG Collection</h1>
        <p className="home-subtitle">
          Search cards, monitor market prices, and manage your portfolio all in one place.
        </p>
        <div className="home-buttons">
          <Link to="/search" className="btn-primary btn-lg">Search Cards</Link>
          <Link to="/portfolio" className="btn-outline btn-lg">My Portfolio</Link>
        </div>
      </div>

      <div className="home-features">
        <div className="feature">
          <div className="feature-icon">🔍</div>
          <h3>Search</h3>
          <p>Find any card by name, set, or number from the full Pokemon TCG catalog.</p>
        </div>
        <div className="feature">
          <div className="feature-icon">📈</div>
          <h3>Live Prices</h3>
          <p>See current market prices pulled from TCGPlayer for every card.</p>
        </div>
        <div className="feature">
          <div className="feature-icon">💼</div>
          <h3>Portfolio</h3>
          <p>Track what you paid vs. what your cards are worth today.</p>
        </div>
      </div>
    </div>
  )
}
