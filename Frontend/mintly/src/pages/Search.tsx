import { useState, useEffect, useRef } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import {
  searchCards,
  filterCards,
  getSets,
  getCardPrice,
  type Card,
  type CardSet,
} from "../api";
import CardImage from "../components/CardImage";
import DayChange from "../components/DayChange";
import PriceQtyForm from "../components/PriceQtyForm";
import PortfolioPicker from "../components/PortfolioPicker";
import StatusMessage from "../components/StatusMessage";
import { useAddCard } from "../hooks";
import { usePortfolios } from "../portfolios";
import { getOwnedQty } from "../owned";
import { money } from "../format";
import styles from "./Search.module.css";

const RARITIES = [
  "Common",
  "Uncommon",
  "Rare",
  "Rare Holo",
  "Rare Holo EX",
  "Rare Holo GX",
  "Rare Holo V",
  "Rare Holo VMAX",
  "Double Rare",
  "Illustration Rare",
  "Special Illustration Rare",
  "Rare Ultra",
  "Rare Secret",
  "Rare Rainbow",
  "Hyper Rare",
  "Amazing Rare",
  "Radiant Rare",
  "Promo",
];

const TYPES = [
  "Colorless",
  "Darkness",
  "Dragon",
  "Fairy",
  "Fighting",
  "Fire",
  "Grass",
  "Lightning",
  "Metal",
  "Psychic",
  "Water",
];

// Comma-joined URL param -> list of values (the multi-select facets)
function parseList(v: string | null): string[] {
  return v ? v.split(",").filter(Boolean) : [];
}

// "2024/11/08" (or ISO) -> "Nov 8, 2024" for the default-view sub-line
function formatSetDate(d?: string) {
  if (!d) return "";
  const date = new Date(d.replace(/\//g, "-") + (d.length <= 10 ? "T00:00:00" : ""));
  return Number.isNaN(date.getTime())
    ? d
    : date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

const SearchIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" aria-hidden="true">
    <circle cx="11" cy="11" r="6.5" />
    <path d="M16 16l4.5 4.5" />
  </svg>
);

const PlusIcon = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
    <path d="M12 5v14M5 12h14" />
  </svg>
);

const FilterIcon = () => (
  <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" aria-hidden="true">
    <path d="M4 6h16M7 12h10M10 18h4" />
  </svg>
);

export default function Search() {
  // Seed query + filters from the URL (?q=, ?set=, ?rarity=, ?type=, ?number=)
  // so the home hero's ?q= link, shared URLs, and — crucially — pressing Back
  // from a card all restore the exact search. The effect below keeps the URL in
  // sync; the debounce effect then runs it like any typed query.
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const initialPage = Math.max(1, Number(searchParams.get("page")) || 1);
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [sets, setSets] = useState<CardSet[]>([]);
  // set/rarity/type are multi-select — each holds a list of chosen values
  const [setIds, setSetIds] = useState<string[]>(() => parseList(searchParams.get("set")));
  const [rarities, setRarities] = useState<string[]>(() => parseList(searchParams.get("rarity")));
  const [types, setTypes] = useState<string[]>(() => parseList(searchParams.get("type")));
  const [number, setNumber] = useState(searchParams.get("number") ?? "");
  // Rarity / type / card # collapse behind a "Filters" button; sets stay
  // exposed. Open the panel on mount if any of those arrived seeded in the URL
  // (a shared link or Back from a card) so the applied filters are visible.
  const [filtersOpen, setFiltersOpen] = useState(
    () =>
      parseList(searchParams.get("rarity")).length > 0 ||
      parseList(searchParams.get("type")).length > 0 ||
      !!(searchParams.get("number") ?? "").trim(),
  );
  const [cards, setCards] = useState<Card[]>([]);
  const [page, setPage] = useState(initialPage);
  const [totalCount, setTotalCount] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  // Seed `loading` true when the URL already carries a query or filters: a search
  // is guaranteed to fire (via the debounce effect below), so start on skeletons
  // rather than flashing the "No cards match" empty state during the debounce.
  const [loading, setLoading] = useState(
    () =>
      !!(searchParams.get("q") ?? "").trim() ||
      parseList(searchParams.get("set")).length > 0 ||
      parseList(searchParams.get("rarity")).length > 0 ||
      parseList(searchParams.get("type")).length > 0 ||
      !!(searchParams.get("number") ?? "").trim(),
  );
  const [error, setError] = useState("");
  const [adding, setAdding] = useState<string | null>(null);
  const [purchasePrice, setPurchasePrice] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [addTarget, setAddTarget] = useState<number | null>(null);
  const [ownedQty, setOwnedQty] = useState<Map<string, number>>(new Map());
  const { add: addToPortfolio, busy: addBusy, status: addStatus } = useAddCard();
  const { activeId } = usePortfolios();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // The first search after mount honors the URL's ?page= (so Back from a card
  // lands on the same page); every later query/filter change restarts at page 1.
  const firstRunRef = useRef(true);

  const hasFilters = !!(setIds.length || rarities.length || types.length || number.trim());
  // How many of the collapsed (non-set) filters are active — drives the badge
  const advancedCount = rarities.length + types.length + (number.trim() ? 1 : 0);
  const isDefaultView = !query.trim() && !hasFilters;

  // Sets power the filter dropdown and the default view (newest set)
  useEffect(() => {
    getSets()
      .then((data) => {
        const sorted = [...data].sort((a, b) =>
          (b.releaseDate || "").localeCompare(a.releaseDate || ""),
        );
        setSets(sorted);
      })
      .catch(() => {});
  }, []);

  // Which cards the signed-in user already holds, for the "Owned ×N" badge
  useEffect(() => {
    getOwnedQty().then(setOwnedQty).catch(() => {});
  }, []);

  // Mirror the active query + filters + page into the URL (replace, so typing
  // doesn't pile up history entries). This is what makes browser Back from a card
  // return to the search — and the page — you had: Search re-seeds its state from
  // these params on mount. page=1 is left off to keep the URL clean.
  useEffect(() => {
    const params: Record<string, string> = {};
    if (query.trim()) params.q = query.trim();
    if (setIds.length) params.set = setIds.join(",");
    if (rarities.length) params.rarity = rarities.join(",");
    if (types.length) params.type = types.join(",");
    if (number.trim()) params.number = number.trim();
    if (page > 1) params.page = String(page);
    setSearchParams(params, { replace: true });
  }, [query, setIds, rarities, types, number, page, setSearchParams]);

  async function runSearch(p: number) {
    setLoading(true);
    setError("");
    setAdding(null);
    try {
      let results;
      if (hasFilters) {
        results = await filterCards(
          {
            name: query.trim() || undefined,
            set_id: setIds.length ? setIds : undefined,
            rarity: rarities.length ? rarities : undefined,
            type: types.length ? types : undefined,
            number: number.trim() || undefined,
          },
          p,
        );
      } else if (query.trim()) {
        results = await searchCards(query, p);
      } else {
        // Nothing typed and no filters — show the newest set by default
        results = await filterCards({ set_id: sets[0].id }, p);
      }
      setCards(results.data);
      setPage(p);
      setTotalCount(results.totalCount);
      setPageSize(results.pageSize || 50);
    } catch {
      setCards([]);
      setError(
        isDefaultView
          ? "We couldn't load cards right now. Check your internet connection and try again in a moment."
          : "We couldn't complete that search. Check your internet connection and try again in a moment.",
      );
    } finally {
      setLoading(false);
    }
  }

  // Query/filter changes always restart from page 1; only Prev/Next move it.
  // The very first run honors the URL's seeded page (Back from a card / shared
  // link); firstRunRef flips once that run actually fires.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const run = () => {
      const target = firstRunRef.current ? initialPage : 1;
      firstRunRef.current = false;
      runSearch(target);
    };
    if (!query.trim() && !hasFilters) {
      if (sets.length > 0) {
        debounceRef.current = setTimeout(run, 0);
      }
    } else {
      debounceRef.current = setTimeout(run, 400); //400 ms debounce
    }
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, setIds, rarities, types, number, sets]);

  function handleSearch(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (query.trim() || hasFilters) runSearch(1);
  }

  function goToPage(p: number) {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    runSearch(p);
    window.scrollTo({ top: 0 });
  }

  function clearFilters() {
    setSetIds([]);
    setRarities([]);
    setTypes([]);
    setNumber("");
  }

  const addSet = (v: string) => setSetIds((p) => (p.includes(v) ? p : [...p, v]));
  const removeSet = (v: string) => setSetIds((p) => p.filter((x) => x !== v));
  const addRarity = (v: string) => setRarities((p) => (p.includes(v) ? p : [...p, v]));
  const removeRarity = (v: string) => setRarities((p) => p.filter((x) => x !== v));
  const addType = (v: string) => setTypes((p) => (p.includes(v) ? p : [...p, v]));
  const removeType = (v: string) => setTypes((p) => p.filter((x) => x !== v));

  function handleAdd(card: Card) {
    addToPortfolio(card.id, purchasePrice, quantity, addTarget ?? activeId, () => {
      setAdding(null);
      setPurchasePrice("");
      setQuantity("1");
      // useAddCard already invalidated the owned cache — refresh the badge
      getOwnedQty().then(setOwnedQty).catch(() => {});
    });
  }

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const newestSet = sets[0];
  const setName = (id: string) => sets.find((s) => s.id === id)?.name ?? id;

  const pager = totalPages > 1 && cards.length > 0 && !error && (
    <div className={styles.pagination}>
      <button
        className={styles.pagerBtn}
        disabled={page <= 1 || loading}
        onClick={() => goToPage(page - 1)}
      >
        ← Prev
      </button>
      <span className={`${styles.pageInfo} num`}>
        Page {page} of {totalPages} · {totalCount.toLocaleString()} cards
      </span>
      <button
        className={styles.pagerBtn}
        disabled={page >= totalPages || loading}
        onClick={() => goToPage(page + 1)}
      >
        Next →
      </button>
    </div>
  );

  // A multi-select facet: a `<select>` chip that stays put so you can keep
  // adding, plus one dismissible accent chip per chosen value (a styled
  // `<select>` can't hold a working ✕, so each pick becomes its own chip).
  // Already-picked options drop out of the dropdown.
  const multiFilter = (
    values: string[],
    placeholder: string,
    options: { value: string; label: string }[],
    labelFor: (v: string) => string,
    onAdd: (v: string) => void,
    onRemove: (v: string) => void,
  ) => (
    <>
      <span className={styles.selectChip}>
        <select value="" onChange={(e) => e.target.value && onAdd(e.target.value)} aria-label={placeholder}>
          <option value="">{placeholder}</option>
          {options
            .filter((o) => !values.includes(o.value))
            .map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
        </select>
        <span className={styles.chevron} aria-hidden="true">▾</span>
      </span>
      {values.map((v) => (
        <button key={v} className={styles.chipActive} onClick={() => onRemove(v)}>
          {labelFor(v)} <span className={styles.chipX}>✕</span>
        </button>
      ))}
    </>
  );

  return (
    <div className="page">
      <form onSubmit={handleSearch} className={styles.searchPill}>
        <span className={styles.searchGlyph}>
          <SearchIcon />
        </span>
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name, e.g. Charizard"
          aria-label="Search cards by name"
          className={styles.searchInput}
        />
        {query && (
          <button
            type="button"
            className={styles.clearBtn}
            aria-label="Clear search"
            onClick={() => {
              setQuery("");
              inputRef.current?.focus();
            }}
          >
            ✕
          </button>
        )}
        <button type="submit" className={styles.searchSubmit} disabled={loading}>
          {loading ? "Searching…" : "Search"}
        </button>
      </form>

      <div className={styles.filterRow}>
        <button
          type="button"
          className={`${styles.filterToggle} ${filtersOpen ? styles.filterToggleOpen : ""}`}
          aria-expanded={filtersOpen}
          aria-controls="more-filters"
          onClick={() => setFiltersOpen((o) => !o)}
        >
          <FilterIcon /> Filters
          {advancedCount > 0 && <span className={styles.filterBadge}>{advancedCount}</span>}
        </button>
        {multiFilter(
          setIds,
          "All sets",
          sets.map((s) => ({ value: s.id, label: s.name })),
          setName,
          addSet,
          removeSet,
        )}
        {hasFilters && (
          <button className={styles.clearFilters} onClick={clearFilters}>
            Clear
          </button>
        )}
        {!isDefaultView && !loading && !error && totalCount > 0 && (
          <span className={`${styles.filterCount} num`}>{totalCount.toLocaleString()} results</span>
        )}
      </div>

      {filtersOpen && (
        <div className={styles.moreFilters} id="more-filters">
          {multiFilter(
            rarities,
            "Any rarity",
            RARITIES.map((r) => ({ value: r, label: r })),
            (r) => r,
            addRarity,
            removeRarity,
          )}
          {multiFilter(
            types,
            "Any type",
            TYPES.map((t) => ({ value: t, label: t })),
            (t) => t,
            addType,
            removeType,
          )}
          <input
            value={number}
            onChange={(e) => setNumber(e.target.value)}
            placeholder="Card #"
            aria-label="Card number"
            className={styles.numberChip}
          />
        </div>
      )}

      {/* Header: browse-the-newest-set eyebrow (default) or a results title */}
      {isDefaultView ? (
        newestSet && (
          <div className={styles.defaultHead}>
            <span className={styles.eyebrow}>Newest set</span>
            <h1 className={styles.defaultTitle}>{newestSet.name}</h1>
            <p className={`${styles.defaultSub} num`}>
              Released {formatSetDate(newestSet.releaseDate)} · {totalCount.toLocaleString()} cards
            </p>
          </div>
        )
      ) : (
        <div className={styles.resultsHead}>
          <h1 className={styles.resultsTitle}>
            {query.trim() ? `Results for “${query.trim()}”` : "Results"}
          </h1>
          {!error && cards.length > 0 && (
            <span className={`${styles.resultsMeta} num`}>
              Page {page} of {totalPages}
              {query.trim() ? " · sorted by relevance" : ""}
            </span>
          )}
        </div>
      )}

      {error && <p className="error">{error}</p>}

      {!loading &&
        cards.length > 0 &&
        cards.every((c) => getCardPrice(c) == null) && (
          <p className="prices-note">
            {cards.some((c) => c.estimate)
              ? "TCGPlayer market prices aren't available for this set yet. Values marked \"eBay est.\" are estimates from recent eBay sales."
              : "Market prices aren't available for these cards yet. The price data source hasn't been updated for this set."}
          </p>
        )}

      {pager}

      {loading && cards.length === 0 ? (
        <div className={styles.cardGrid}>
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className={styles.skeleton}>
              <div className={styles.skeletonArt} />
              <div className={styles.skeletonBar} style={{ width: "70%" }} />
              <div className={styles.skeletonBar} style={{ width: "45%" }} />
            </div>
          ))}
        </div>
      ) : !loading && !error && cards.length === 0 && !isDefaultView ? (
        <div className={styles.noResults}>
          <p className={styles.noResultsTitle}>
            No cards match {query.trim() ? `“${query.trim()}”` : "those filters"}
          </p>
          <p className={styles.noResultsHint}>
            Check the spelling, or try a shorter search like just the card's name.
          </p>
          {hasFilters && (
            <button className={styles.clearFiltersPill} onClick={clearFilters}>
              Clear filters
            </button>
          )}
        </div>
      ) : (
        <div className={styles.cardGrid}>
          {cards.map((card) => {
            const price = getCardPrice(card);
            const est = price == null ? card.estimate?.value ?? null : null;
            const owned = ownedQty.get(card.id);
            const isAdding = adding === card.id;
            const status = addStatus?.id === card.id ? addStatus : null;

            return (
              <div key={card.id} className={styles.tile}>
                <Link
                  to={`/card/${card.id}`}
                  state={{ backSearch: location.search }}
                  className={styles.tileLink}
                >
                  <span className={styles.tileArt}>
                    <CardImage src={card.images.small} alt={card.name} />
                    {owned ? (
                      <span className={`${styles.ownedBadge} num`}>✓ Owned ×{owned}</span>
                    ) : null}
                  </span>
                  <div>
                    <p className={styles.tileName}>{card.name}</p>
                    <p className={styles.tileMeta}>
                      {card.set.name}
                      {card.number ? ` · #${card.number}` : ""}
                    </p>
                  </div>
                  <div className={`${styles.tilePrice} num`}>
                    {price != null ? (
                      <>
                        <span className={styles.priceNum}>{money(price)}</span>
                        {card.priceChange && <DayChange change={card.priceChange} />}
                      </>
                    ) : est != null ? (
                      <span className={styles.priceNum}>
                        {money(est)}
                        <span className={styles.estLabel}>eBay est.</span>
                      </span>
                    ) : (
                      <span className={styles.priceNone}>—</span>
                    )}
                  </div>
                </Link>

                {status ? (
                  <StatusMessage ok={status.ok}>{status.msg}</StatusMessage>
                ) : isAdding ? (
                  <div className={styles.quickAdd}>
                    <PortfolioPicker
                      value={addTarget}
                      onChange={setAddTarget}
                      label="Add to"
                    />
                    <PriceQtyForm
                      className={styles.quickAddForm}
                      price={purchasePrice}
                      quantity={quantity}
                      onPriceChange={setPurchasePrice}
                      onQuantityChange={setQuantity}
                      onSubmit={() => handleAdd(card)}
                      submitLabel="Add"
                      busyLabel="Adding…"
                      busy={addBusy}
                      smallButtons
                      onCancel={() => {
                        setAdding(null);
                        setPurchasePrice("");
                        setQuantity("1");
                      }}
                    />
                  </div>
                ) : (
                  <button
                    className={styles.tileBtn}
                    onClick={() => {
                      setAdding(card.id);
                      setAddTarget(activeId);
                      // Priceless cards can't fall back to a market price on
                      // add — seed the form with the eBay estimate instead
                      if (price == null && est != null) {
                        setPurchasePrice(est.toFixed(2));
                      }
                    }}
                  >
                    <PlusIcon /> Portfolio
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {pager}
    </div>
  );
}
