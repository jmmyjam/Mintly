import { Link } from "react-router-dom";
import HeroSearch from "../components/HeroSearch";
import styles from "./Home.module.css";

export default function Home() {
  return (
    <div className={styles.home}>
      <div className={styles.homeHero}>
        <div className={styles.homeHeroLeft}>
          <h1 className={styles.homeTitle}>
            Your cards. Their prices. One portfolio.
          </h1>
          <HeroSearch />
          <div className={styles.homeHeroDivider} />
          <p className={styles.homeSubtitle}>
            Mintly tracks every card you own against live TCGPlayer prices.
            Search the full catalog, add your cards, and watch your portfolio's
            value build over time.
          </p>
        </div>
        <div className={styles.homeHeroCards} aria-hidden="true">
          <img
            className={`${styles.heroCard} ${styles.heroCard1}`}
            src="https://images.pokemontcg.io/sv3pt5/200_hires.png"
            alt=""
            loading="lazy"
          />
          <img
            className={`${styles.heroCard} ${styles.heroCard2}`}
            src="https://images.pokemontcg.io/sv3pt5/199_hires.png"
            alt=""
          />
          <img
            className={`${styles.heroCard} ${styles.heroCard3}`}
            src="https://images.pokemontcg.io/sv3pt5/198_hires.png"
            alt=""
            loading="lazy"
          />
        </div>
      </div>

      <div className={styles.homeFeatures}>
        <div className={styles.feature}>
          <div className={styles.featureNum}>01</div>
          <h3>Search</h3>
          <p>
            Find any card by name, set, or number from the full Pokemon TCG
            catalog.
          </p>
        </div>
        <div className={styles.feature}>
          <div className={styles.featureNum}>02</div>
          <h3>Live Prices</h3>
          <p>See current market prices pulled from TCGPlayer for every card.</p>
        </div>
        <div className={styles.feature}>
          <div className={styles.featureNum}>03</div>
          <h3>Portfolio</h3>
          <p>Track what you paid vs. what your cards are worth today.</p>
        </div>
      </div>

      <section className={styles.scanSection}>
        <div className={styles.scanCopy}>
          <span className={styles.scanEyebrow}>Camera scanner</span>
          <h2 className={styles.scanTitle}>Scan any card with your camera</h2>
          <p className={styles.scanText}>
            Point your phone at a card and Mintly identifies it instantly,
            matching the photo against its full catalog, then add it to your
            portfolio in a tap. No typing set names or hunting for card numbers.
          </p>
          <div className={styles.scanBadges}>
            <span className={styles.scanBadge}>✓ Free forever</span>
            <span className={styles.scanBadge}>✓ Unlimited scans</span>
          </div>
          <p className={styles.scanFinePrint}>
            No scan limits, no credits, no cost.
          </p>
          <Link to="/scan" className="btn-primary btn-lg">
            Scan a card
          </Link>
        </div>
        <div className={styles.scanVisual} aria-hidden="true">
          <div className={styles.scanFrame}>
            <img
              className={styles.scanCardImg}
              src="https://images.scrydex.com/pokemon/me2pt5-276/large"
              alt=""
              loading="lazy"
            />
            <span className={`${styles.scanCorner} ${styles.scanCornerTl}`} />
            <span className={`${styles.scanCorner} ${styles.scanCornerTr}`} />
            <span className={`${styles.scanCorner} ${styles.scanCornerBl}`} />
            <span className={`${styles.scanCorner} ${styles.scanCornerBr}`} />
          </div>
        </div>
      </section>

      <div className={styles.homeCta}>
        <div>
          <h2>Start tracking your collection.</h2>
          <p>
            Add your cards once, and Mintly keeps the prices and history up to
            date.
          </p>
        </div>
        <Link to="/portfolio" className="btn-primary btn-lg">
          Open my portfolio
        </Link>
      </div>
    </div>
  );
}
