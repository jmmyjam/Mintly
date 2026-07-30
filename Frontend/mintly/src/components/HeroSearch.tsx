import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAccessibility } from "../accessibility";
import styles from "./HeroSearch.module.css";

// Real queries the smart search handles well (name + set name combos)
const EXAMPLES = [
  "charizard base",
  "greninja chaos rising",
  "pikachu vmax",
  "gengar ascended heroes",
  "eevee prismatic evolutions",
];

const QUICK_SEARCHES = [
  "Charizard",
  "Pikachu VMAX",
  "Prismatic Evolutions",
  "Umbreon",
];

const SearchIcon = () => (
  <svg
    viewBox="0 0 24 24"
    width="20"
    height="20"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.9"
    strokeLinecap="round"
    aria-hidden="true"
  >
    <circle cx="11" cy="11" r="6.5" />
    <path d="M16 16l4.5 4.5" />
  </svg>
);

// Typewriter effect for the placeholder: type an example, pause, erase, next.
// All state updates happen inside timeout callbacks (strict react-hooks rule).
// Disabled (returns "") when `enabled` is false, so reduce-motion gets a static
// placeholder instead of an animated one.
function useTypingPlaceholder(examples: string[], enabled: boolean) {
  const [text, setText] = useState("");
  const [index, setIndex] = useState(0);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    const full = examples[index];
    const delay = deleting ? 35 : text === full ? 2000 : 75;
    const timer = setTimeout(() => {
      if (!deleting) {
        if (text === full) setDeleting(true);
        else setText(full.slice(0, text.length + 1));
      } else if (text === "") {
        setDeleting(false);
        setIndex((index + 1) % examples.length);
      } else {
        setText(full.slice(0, text.length - 1));
      }
    }, delay);
    return () => clearTimeout(timer);
  }, [text, deleting, index, examples, enabled]);

  return text;
}

// The home hero's search pill: submitting hands the query to the Search page
// via /search?q=, where it runs automatically.
export default function HeroSearch() {
  const navigate = useNavigate();
  const { settings } = useAccessibility();
  const [value, setValue] = useState("");
  const [focused, setFocused] = useState(false);
  const typed = useTypingPlaceholder(EXAMPLES, !settings.reduceMotion);
  // Reduce-motion gets a static placeholder; otherwise the animated typed string.
  const placeholder = settings.reduceMotion ? 'Try "charizard base"' : typed;
  // The mint-caret overlay stands in for a native placeholder while the field is
  // empty and unfocused; once the user focuses/types, the real input shows.
  const showOverlay = value === "" && !focused;

  function goSearch(query: string) {
    const q = query.trim();
    if (q) navigate(`/search?q=${encodeURIComponent(q)}`);
  }

  return (
    <div className={styles.heroSearchBlock}>
      <form
        className={styles.heroSearch}
        onSubmit={(e) => {
          e.preventDefault();
          goSearch(value);
        }}
      >
        <span className={styles.heroSearchGlyph}>
          <SearchIcon />
        </span>
        <span className={styles.heroSearchField}>
          <input
            className={styles.heroSearchInput}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            aria-label="Search cards by name"
          />
          {showOverlay && (
            <span className={styles.heroSearchPlaceholder} aria-hidden="true">
              {placeholder}
            </span>
          )}
        </span>
        <button type="submit" className={styles.heroSearchBtn}>
          Search
        </button>
      </form>
      <div className={styles.heroChips}>
        <span className={styles.heroChipsLabel}>Try</span>
        {QUICK_SEARCHES.map((q) => (
          <button key={q} className={styles.chip} onClick={() => goSearch(q)}>
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
