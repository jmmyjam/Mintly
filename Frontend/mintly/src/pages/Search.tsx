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
import StatusMessage from "../components/StatusMessage";
import { useAddCard } from "../hooks";
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

export default function Search() {
  // Seed query + filters from the URL (?q=, ?set=, ?rarity=, ?type=, ?number=)
  // so the home hero's ?q= link, shared URLs, and — crucially — pressing Back
  // from a card all restore the exact search. The effect below keeps the URL in
  // sync; the debounce effect then runs it like any typed query.
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [sets, setSets] = useState<CardSet[]>([]);
  const [setId, setSetId] = useState(searchParams.get("set") ?? "");
  const [rarity, setRarity] = useState(searchParams.get("rarity") ?? "");
  const [typeFilter, setTypeFilter] = useState(searchParams.get("type") ?? "");
  const [number, setNumber] = useState(searchParams.get("number") ?? "");
  const [cards, setCards] = useState<Card[]>([]);
  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [resultsLabel, setResultsLabel] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState<string | null>(null);
  const [purchasePrice, setPurchasePrice] = useState("");
  const [quantity, setQuantity] = useState("1");
  const { add: addToPortfolio, busy: addBusy, status: addStatus } = useAddCard();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const hasFilters = !!(setId || rarity || typeFilter || number.trim());

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

  // Mirror the active query + filters into the URL (replace, so typing doesn't
  // pile up history entries). This is what makes browser Back from a card return
  // to the search you had — Search re-seeds its state from these params on mount.
  useEffect(() => {
    const params: Record<string, string> = {};
    if (query.trim()) params.q = query.trim();
    if (setId) params.set = setId;
    if (rarity) params.rarity = rarity;
    if (typeFilter) params.type = typeFilter;
    if (number.trim()) params.number = number.trim();
    setSearchParams(params, { replace: true });
  }, [query, setId, rarity, typeFilter, number, setSearchParams]);

  const isDefaultView = !query.trim() && !hasFilters;

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
            set_id: setId || undefined,
            rarity: rarity || undefined,
            type: typeFilter || undefined,
            number: number.trim() || undefined,
          },
          p,
        );
        setResultsLabel("");
      } else if (query.trim()) {
        results = await searchCards(query, p);
        setResultsLabel("");
      } else {
        // Nothing typed and no filters — show the newest set by default
        const newest = sets[0];
        results = await filterCards({ set_id: newest.id }, p);
        setResultsLabel(`Newest set — ${newest.name}`);
      }
      setCards(results.data);
      setPage(p);
      setTotalCount(results.totalCount);
      setPageSize(results.pageSize || 50);
      if (results.totalCount === 0 && !isDefaultView) setError("No cards found.");
    } catch {
      setError(
        isDefaultView
          ? "Failed to load cards. Make sure the server is running."
          : "Search failed. Make sure the server is running.",
      );
    } finally {
      setLoading(false);
    }
  }

  // Query/filter changes always restart from page 1; only Prev/Next move it
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!query.trim() && !hasFilters) {
      if (sets.length > 0) {
        debounceRef.current = setTimeout(() => runSearch(1), 0);
      }
    } else {
      debounceRef.current = setTimeout(() => runSearch(1), 400); //400 ms debounce
    }
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, setId, rarity, typeFilter, number, sets]);

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
    setSetId("");
    setRarity("");
    setTypeFilter("");
    setNumber("");
  }

  function handleAdd(card: Card) {
    addToPortfolio(card.id, purchasePrice, quantity, () => {
      setAdding(null);
      setPurchasePrice("");
      setQuantity("1");
    });
  }

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const pager = totalPages > 1 && cards.length > 0 && !error && (
    <div className={styles.pagination}>
      <button
        className="btn-outline btn-sm"
        disabled={page <= 1 || loading}
        onClick={() => goToPage(page - 1)}
      >
        ← Prev
      </button>
      <span className={styles.pageInfo}>
        Page {page} of {totalPages} · {totalCount.toLocaleString()} cards
      </span>
      <button
        className="btn-outline btn-sm"
        disabled={page >= totalPages || loading}
        onClick={() => goToPage(page + 1)}
      >
        Next →
      </button>
    </div>
  );

  return (
    <div className="page">
      <h1>Search Cards</h1>
      <form onSubmit={handleSearch} className={styles.searchForm}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name (e.g. Charizard)"
          className={styles.searchInput}
        />
        <button type="submit" className="btn-primary" disabled={loading}>
          {loading ? "Searching..." : "Search"}
        </button>
      </form>

      <div className="filter-row">
        <select
          value={setId}
          onChange={(e) => setSetId(e.target.value)}
          className="filter-select"
        >
          <option value="">All sets</option>
          {sets.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <select
          value={rarity}
          onChange={(e) => setRarity(e.target.value)}
          className="filter-select"
        >
          <option value="">Any rarity</option>
          {RARITIES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="filter-select"
        >
          <option value="">Any type</option>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <input
          value={number}
          onChange={(e) => setNumber(e.target.value)}
          placeholder="Card #"
          className={`filter-select ${styles.filterNumber}`}
        />
        {hasFilters && (
          <button className="btn-outline btn-sm" onClick={clearFilters}>
            Clear filters
          </button>
        )}
      </div>

      {error && <p className="error">{error}</p>}

      {resultsLabel && !loading && !error && (
        <h2 className={styles.resultsLabel}>{resultsLabel}</h2>
      )}

      {!loading &&
        cards.length > 0 &&
        cards.every((c) => getCardPrice(c) == null) && (
          <p className="prices-note">
            {cards.some((c) => c.estimate)
              ? "TCGPlayer market prices aren't available for this set yet — values marked \"eBay est.\" are estimates from recent eBay sales."
              : "Market prices aren't available for these cards yet — the price data source hasn't been updated for this set."}
          </p>
        )}

      {pager}

      <div className={styles.cardGrid}>
        {cards.map((card) => {
          const price = getCardPrice(card);
          const isAdding = adding === card.id;
          const status = addStatus?.id === card.id ? addStatus : null;

          return (
            <div key={card.id} className={styles.cardItem}>
              <Link to={`/card/${card.id}`} state={{ backSearch: location.search }} className="card-link">
                <CardImage src={card.images.small} alt={card.name} />
                <div className={styles.cardInfo}>
                  <p className="card-name">{card.name}</p>
                  <p className="card-set">{card.set.name}</p>
                  {price != null ? (
                    <p className={styles.cardPrice}>
                      {money(price)}
                      {card.priceChange && <DayChange change={card.priceChange} className="card-price-change" />}
                    </p>
                  ) : card.estimate ? (
                    // No TCGPlayer price — recent-eBay-sold estimate, styled
                    // like a normal price with the source named beside it
                    <p className={styles.cardPrice}>
                      {money(card.estimate.value)}
                      <span className={styles.estBadge}>eBay est.</span>
                      {card.priceChange && <DayChange change={card.priceChange} className="card-price-change" />}
                    </p>
                  ) : null}
                </div>
              </Link>

              {status && <StatusMessage ok={status.ok}>{status.msg}</StatusMessage>}

              {!status &&
                (isAdding ? (
                  <PriceQtyForm
                    price={purchasePrice}
                    quantity={quantity}
                    onPriceChange={setPurchasePrice}
                    onQuantityChange={setQuantity}
                    onSubmit={() => handleAdd(card)}
                    submitLabel="Add"
                    busyLabel="Adding..."
                    busy={addBusy}
                    smallButtons
                    onCancel={() => {
                      setAdding(null);
                      setPurchasePrice("");
                      setQuantity("1");
                    }}
                  />
                ) : (
                  <button
                    className="btn-outline btn-sm"
                    onClick={() => {
                      setAdding(card.id);
                      // Priceless cards can't fall back to a market price on
                      // add — seed the form with the eBay estimate instead
                      if (price == null && card.estimate) {
                        setPurchasePrice(card.estimate.value.toFixed(2));
                      }
                    }}
                  >
                    + Portfolio
                  </button>
                ))}
            </div>
          );
        })}
      </div>

      {pager}
    </div>
  );
}
