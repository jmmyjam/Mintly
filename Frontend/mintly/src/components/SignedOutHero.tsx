import { Link } from "react-router-dom";
import { getCardImageUrl } from "../api";
import styles from "./SignedOutHero.module.css";

// Promotional surface shown in place of a plain login prompt when a signed-out
// user lands on an account-only page (Portfolio, Scan). Both variants share the
// same full-bleed shell — a blurred, scrimmed card-art backdrop with the pitch
// pulled up over it ("the gate shows what it's gating") — and the same cream
// Log in CTA; they differ only in the pitch content (a fanned card trio for
// portfolio, a numbered how-it-works + dead viewfinder for scan).

interface SignedOutHeroProps {
  variant: "scan" | "portfolio";
}

// Real card art blurred behind the gate — art only, no numbers or prices.
const CARD_BACKDROP = [
  "sv3pt5-199",
  "sv3pt5-200",
  "sv3pt5-198",
  "base1-4",
  "base1-2",
  "base1-15",
];

// The three steps of the scan flow, answering "what happens when I log in".
const SCAN_STEPS = [
  {
    lead: "Frame the card.",
    rest: "The viewfinder locks on when it’s readable.",
  },
  {
    lead: "Confirm the match.",
    rest: "Pick from candidates if it’s a close call.",
  },
  { lead: "Queue the stack.", rest: "Batch mode adds the whole pile at once." },
];

export default function SignedOutHero({ variant }: SignedOutHeroProps) {
  return variant === "scan" ? <ScanHero /> : <PortfolioHero />;
}

// Blurred, scrimmed backdrop of real card art, shared by both gates. Sits behind
// the pitch, which is pulled up over it. Dropped on phones (see the CSS).
function GatedBackdrop() {
  return (
    <>
      <div className={styles.backdrop} aria-hidden="true">
        <div className={styles.backdropGrid}>
          {CARD_BACKDROP.map((id) => (
            <img
              key={id}
              className={styles.backdropCard}
              src={getCardImageUrl(id)}
              alt=""
              loading="lazy"
            />
          ))}
        </div>
      </div>
      <div className={styles.scrim} aria-hidden="true" />
    </>
  );
}

// Shared CTA row: a cream Log in pill plus the register-tab link. Both pages use
// the same button so the two gates read as one system.
function AuthActions({ label }: { label: string }) {
  return (
    <div className={styles.actions}>
      <Link to="/login" className={styles.cta}>
        {label}
      </Link>
      <span className={styles.secondary}>
        New to Mintly?{" "}
        <Link to="/login" state={{ register: true }}>
          Create a free account
        </Link>
      </span>
    </div>
  );
}

function PortfolioHero() {
  return (
    <div className={styles.wrap}>
      <GatedBackdrop />
      <div className={styles.pitch}>
        <div className={styles.pitchInner}>
          <div className={styles.copy}>
            <span className={styles.eyebrow}>Your collection</span>
            <h1 className={styles.title}>
              Track your collection's value over time
            </h1>
            <p className={styles.text}>
              Add the cards you own and Mintly prices them against live
              TCGplayer data, so you see what you paid versus what they're worth
              today, with daily changes and a value-over-time chart.
            </p>
            <div className={styles.badges}>
              <span className={styles.badge}>✓ Live TCGplayer prices</span>
              <span className={styles.badge}>✓ Value history</span>
            </div>
            <AuthActions label="Log in" />
          </div>

          <div className={styles.fan} aria-hidden="true">
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
        </div>
      </div>
    </div>
  );
}

function ScanHero() {
  return (
    <div className={styles.wrap}>
      <GatedBackdrop />
      <div className={styles.pitch}>
        <div className={styles.scanInner}>
          <div className={styles.copy}>
            <span className={styles.eyebrow}>Camera scanner</span>
            <h1 className={`${styles.title} ${styles.titleScan}`}>
              Scan any card,
              <br />
              free and unlimited
            </h1>
            <p className={styles.text}>
              Point your phone at a card and Mintly matches the photo against
              its full catalog, then adds it to your portfolio in a tap. No scan
              limits, no credits, no cost.
            </p>
            <ol className={styles.steps}>
              {SCAN_STEPS.map((s, i) => (
                <li className={styles.step} key={s.lead}>
                  <span className={styles.stepNum} aria-hidden="true">
                    {i + 1}
                  </span>
                  <span className={styles.stepText}>
                    <span className={styles.stepLead}>{s.lead}</span> {s.rest}
                  </span>
                </li>
              ))}
            </ol>
            <AuthActions label="Log in" />
          </div>

          <div className={styles.scanVisual} aria-hidden="true">
            <div className={styles.cameraOff}>
              <svg
                className={styles.cameraIcon}
                viewBox="0 0 24 24"
                width="30"
                height="30"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <rect x="3" y="7" width="18" height="13" rx="3" />
                <path d="M9 7l1.5-3h3L15 7" />
                <circle cx="12" cy="13.5" r="3.2" />
              </svg>
              <span className={styles.cameraOffTitle}>Camera off</span>
              <span className={styles.cameraOffText}>
                Log in and Mintly will ask for camera access. Nothing is
                uploaded until you confirm a match.
              </span>
            </div>
            <span className={`${styles.corner} ${styles.cornerTl}`} />
            <span className={`${styles.corner} ${styles.cornerTr}`} />
            <span className={`${styles.corner} ${styles.cornerBl}`} />
            <span className={`${styles.corner} ${styles.cornerBr}`} />
          </div>
        </div>
      </div>
    </div>
  );
}
