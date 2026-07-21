import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAccessibility } from "../accessibility";
import styles from "./HeroSearch.module.css";

// Real queries the smart search handles well (name + set name combos)
const EXAMPLES = [
  "charizard base",
  "umbreon evolving skies",
  "pikachu vmax",
  "gengar lost origin",
  "eevee prismatic evolutions",
];

const QUICK_SEARCHES = ["Charizard", "Pikachu VMAX", "Prismatic Evolutions"];

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
  const typed = useTypingPlaceholder(EXAMPLES, !settings.reduceMotion);
  const placeholder = settings.reduceMotion ? 'Try "charizard base"' : typed;

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
        <input
          className={styles.heroSearchInput}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder}
          aria-label="Search cards"
        />
        <button type="submit" className={`btn-primary ${styles.heroSearchBtn}`}>
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
