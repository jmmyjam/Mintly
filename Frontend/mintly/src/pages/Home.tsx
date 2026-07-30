import { Link } from "react-router-dom";
import { getToken } from "../api";
import HeroSearch from "../components/HeroSearch";
import styles from "./Home.module.css";

// Rounded catalog size shown in the proof strip. There's no public count
// endpoint (and adding one for a signed-out page isn't worth it), so keep this
// as a conservative constant and bump it as the catalog grows — the real figure
// is on the Admin dashboard under Data health -> "catalog cards".
const CATALOG_SIZE = "21,400+";

export default function Home() {
  const loggedIn = !!getToken();

  return (
    <div className={styles.home}>
      <section className={styles.hero}>
        <div className={styles.heroLeft}>
          <h1 className={styles.title}>
            Your cards.
            <br />
            Their prices.
            <br />
            One portfolio.
          </h1>
          <div className={styles.searchWrap}>
            <HeroSearch />
          </div>
          <p className={styles.subtitle}>
            Track every card you own against live market prices. Free to use, no scan limits, no
            credits.
          </p>
        </div>
        <div className={styles.heroCards} aria-hidden="true">
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
      </section>

      <section className={styles.proof}>
        <div className={styles.proofCell}>
          <div className={`${styles.proofFigure} num`}>{CATALOG_SIZE}</div>
          <div className={styles.proofLabel}>cards in the catalog</div>
        </div>
        <div className={styles.proofCell}>
          <div className={styles.proofFigure}>Daily</div>
          <div className={styles.proofLabel}>price refresh</div>
        </div>
        <div className={styles.proofCell}>
          <div className={styles.proofFigure}>Unlimited</div>
          <div className={styles.proofLabel}>camera scans</div>
        </div>
        <div className={styles.proofCell}>
          <div className={`${styles.proofFigure} num`}>$0</div>
          <div className={styles.proofLabel}>to track your collection</div>
        </div>
      </section>

      <section className={styles.scanSection}>
        <div className={styles.scanCopy}>
          <span className={styles.scanEyebrow}>Camera scanner</span>
          <h2 className={styles.scanTitle}>Scan a stack in one sitting</h2>
          <p className={styles.scanText}>
            Point your phone at a card and Mintly identifies it against the full catalog. Batch mode
            queues card after card, then adds the whole pile to your portfolio at once.
          </p>
          <div className={styles.scanBadges}>
            <span className={styles.scanBadge}>✓ Free forever</span>
            <span className={styles.scanBadge}>✓ Unlimited scans</span>
          </div>
        </div>
        {/* DOM order is copy -> visual -> button so the single-column mobile
            layout reads copy, card, then a full-width button; on desktop the
            three are explicitly grid-placed, so their source order doesn't
            matter (button under the copy, card spanning the right). */}
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
        <Link to="/scan" className={`btn-primary btn-lg ${styles.scanBtn}`}>
          Scan a card
        </Link>
      </section>

      <div className={styles.cta}>
        <div>
          <h2>Start tracking your collection.</h2>
          <p>Add your cards once, and Mintly keeps the prices and history up to date.</p>
        </div>
        {loggedIn ? (
          <Link to="/portfolio" className="btn-primary btn-lg">
            Open my portfolio
          </Link>
        ) : (
          <Link to="/login" state={{ register: true }} className="btn-primary btn-lg">
            Create a free account
          </Link>
        )}
      </div>
    </div>
  );
}
