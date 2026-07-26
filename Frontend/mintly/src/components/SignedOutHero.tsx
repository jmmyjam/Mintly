import { Link } from 'react-router-dom'
import styles from './SignedOutHero.module.css'

// Promotional hero shown in place of the plain login prompt when a signed-out
// user lands on an account-only page (Portfolio, Scan). Sells the feature and
// routes to /login — the "Create a free account" link opens the register tab.

interface SignedOutHeroProps {
  variant: 'scan' | 'portfolio'
}

const COPY = {
  scan: {
    eyebrow: 'Camera scanner',
    title: 'Scan any card, free and unlimited',
    text: 'Point your phone at a Pokémon card and Mintly identifies it instantly, matching the photo against its full catalog, then adds it to your portfolio in a tap. No scan limits, no credits, no cost. Just log in to start.',
    badges: ['✓ Free forever', '✓ Unlimited scans'],
  },
  portfolio: {
    eyebrow: 'Your collection',
    title: 'Track your collection’s value over time',
    text: 'Add the cards you own and Mintly tracks them against live TCGplayer prices, so you can see what you paid versus what they’re worth today, with daily changes and a value-over-time chart. Log in to build your portfolio.',
    badges: ['✓ Live TCGplayer prices', '✓ Value history'],
  },
} as const

export default function SignedOutHero({ variant }: SignedOutHeroProps) {
  const copy = COPY[variant]

  return (
    <div className="page">
      <section className={styles.hero}>
        <div className={styles.copy}>
          <span className={styles.eyebrow}>{copy.eyebrow}</span>
          <h1 className={styles.title}>{copy.title}</h1>
          <p className={styles.text}>{copy.text}</p>
          <div className={styles.badges}>
            {copy.badges.map((b) => (
              <span key={b} className={styles.badge}>
                {b}
              </span>
            ))}
          </div>
          <div className={styles.actions}>
            <Link to="/login" className="btn-primary btn-lg">
              Log in
            </Link>
            <span className={styles.secondary}>
              New to Mintly?{' '}
              <Link to="/login" state={{ register: true }}>
                Create a free account
              </Link>
            </span>
          </div>
        </div>

        <div className={styles.visual} aria-hidden="true">
          {variant === 'scan' ? <ScanVisual /> : <PortfolioVisual />}
        </div>
      </section>
    </div>
  )
}

// Decorative viewfinder — echoes the real /scan card-outline frame (mirrors the
// Home page's scanner visual).
function ScanVisual() {
  return (
    <div className={styles.frame}>
      <img
        className={styles.frameImg}
        src="https://images.scrydex.com/pokemon/me2pt5-276/large"
        alt=""
        loading="lazy"
      />
      <span className={`${styles.corner} ${styles.cornerTl}`} />
      <span className={`${styles.corner} ${styles.cornerTr}`} />
      <span className={`${styles.corner} ${styles.cornerBl}`} />
      <span className={`${styles.corner} ${styles.cornerBr}`} />
    </div>
  )
}

// Fanned spread of the 151-set Special Illustration Rares — same trio as the
// Home hero, so the two promotional surfaces read as one system.
function PortfolioVisual() {
  return (
    <div className={styles.fan}>
      <img
        className={`${styles.fanCard} ${styles.fanCard1}`}
        src="https://images.pokemontcg.io/sv3pt5/200_hires.png"
        alt=""
        loading="lazy"
      />
      <img
        className={`${styles.fanCard} ${styles.fanCard2}`}
        src="https://images.pokemontcg.io/sv3pt5/199_hires.png"
        alt=""
        loading="lazy"
      />
      <img
        className={`${styles.fanCard} ${styles.fanCard3}`}
        src="https://images.pokemontcg.io/sv3pt5/198_hires.png"
        alt=""
        loading="lazy"
      />
    </div>
  )
}
