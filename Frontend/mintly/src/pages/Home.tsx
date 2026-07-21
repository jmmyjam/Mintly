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
            Mintly tracks every card you own against live TCGPlayer prices —
            search the full catalog, add your cards, and watch your
            portfolio's value build over time.
          </p>
        </div>
        <div className={styles.homeHeroCards} aria-hidden="true">
          <img
            className={`${styles.heroCard} ${styles.heroCard1}`}
            src="https://images.pokemontcg.io/base1/2_hires.png"
            alt=""
            loading="lazy"
          />
          <img
            className={`${styles.heroCard} ${styles.heroCard2}`}
            src="https://images.pokemontcg.io/base1/4_hires.png"
            alt=""
          />
          <img
            className={`${styles.heroCard} ${styles.heroCard3}`}
            src="https://images.pokemontcg.io/base1/15_hires.png"
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

      <div className={styles.homeCta}>
        <div>
          <h2>Start tracking your collection.</h2>
          <p>
            Add your cards once — Mintly keeps the prices and history up to
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
