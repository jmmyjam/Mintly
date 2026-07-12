import { useState, useEffect, useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  searchCards,
  filterCards,
  getSets,
  addCard,
  getToken,
  getCardPrice,
  SessionExpiredError,
  type Card,
  type CardSet,
} from "../api";

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
  const [query, setQuery] = useState("");
  const [sets, setSets] = useState<CardSet[]>([]);
  const [setId, setSetId] = useState("");
  const [rarity, setRarity] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [number, setNumber] = useState("");
  const [cards, setCards] = useState<Card[]>([]);
  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [pageSize, setPageSize] = useState(250);
  const [resultsLabel, setResultsLabel] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState<string | null>(null);
  const [addBusy, setAddBusy] = useState(false);
  const [purchasePrice, setPurchasePrice] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [addStatus, setAddStatus] = useState<{
    id: string;
    msg: string;
    ok: boolean;
  } | null>(null);
  const navigate = useNavigate();
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
      setPageSize(results.pageSize || 250);
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

  async function handleAdd(card: Card) {
    if (!getToken()) {
      navigate("/login");
      return;
    }
    if (addBusy) return;
    setAddBusy(true);
    try {
      const price = parseFloat(purchasePrice);
      const msg = await addCard(
        card.id,
        Number.isNaN(price) ? null : price,
        parseInt(quantity) || 1,
      );
      setAdding(null);
      setPurchasePrice("");
      setQuantity("1");
      setAddStatus({ id: card.id, msg, ok: true });
      setTimeout(() => setAddStatus(null), 3000);
    } catch (err: unknown) {
      if (err instanceof SessionExpiredError) {
        navigate("/login", {
          state: { notice: "Your session expired — please log in again." },
        });
        return;
      }
      const msg = err instanceof Error ? err.message : "Failed to add card";
      setAddStatus({ id: card.id, msg, ok: false });
      setTimeout(() => setAddStatus(null), 4000);
    } finally {
      setAddBusy(false);
    }
  }

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const pager = totalPages > 1 && cards.length > 0 && !error && (
    <div className="pagination">
      <button
        className="btn-outline btn-sm"
        disabled={page <= 1 || loading}
        onClick={() => goToPage(page - 1)}
      >
        ← Prev
      </button>
      <span className="page-info">
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
      <form onSubmit={handleSearch} className="search-form">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name (e.g. Charizard)"
          className="search-input"
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
          className="filter-select filter-number"
        />
        {hasFilters && (
          <button className="btn-outline btn-sm" onClick={clearFilters}>
            Clear filters
          </button>
        )}
      </div>

      {error && <p className="error">{error}</p>}

      {resultsLabel && !loading && !error && (
        <h2 className="results-label">{resultsLabel}</h2>
      )}

      {!loading &&
        cards.length > 0 &&
        cards.every((c) => getCardPrice(c) == null) && (
          <p className="prices-note">
            Market prices aren't available for these cards yet — the price data
            source hasn't been updated for this set.
          </p>
        )}

      {pager}

      <div className="card-grid">
        {cards.map((card) => {
          const price = getCardPrice(card);
          const isAdding = adding === card.id;
          const status = addStatus?.id === card.id ? addStatus : null;

          return (
            <div key={card.id} className="card-item">
              <Link to={`/card/${card.id}`} className="card-link">
                <img
                  src={card.images.small}
                  alt={card.name}
                  className="card-image"
                  loading="lazy"
                />
                <div className="card-info">
                  <p className="card-name">{card.name}</p>
                  <p className="card-set">{card.set.name}</p>
                  {price != null && (
                    <p className="card-price">${price.toFixed(2)}</p>
                  )}
                </div>
              </Link>

              {status && (
                <p className={status.ok ? "success-msg" : "error"}>
                  {status.msg}
                </p>
              )}

              {!status &&
                (isAdding ? (
                  <form
                    className="add-form"
                    onSubmit={(e) => {
                      e.preventDefault();
                      handleAdd(card);
                    }}
                  >
                    <input
                      type="number"
                      placeholder="Price paid($)"
                      value={purchasePrice}
                      onChange={(e) => setPurchasePrice(e.target.value)}
                      className="mini-input"
                      min="0"
                      step="0.01"
                    />
                    <input
                      type="number"
                      placeholder="Qty"
                      value={quantity}
                      onChange={(e) => setQuantity(e.target.value)}
                      className="mini-input mini-qty"
                      min="1"
                    />
                    <div className="add-form-buttons">
                      <button
                        type="submit"
                        className="btn-primary btn-sm"
                        disabled={addBusy}
                      >
                        {addBusy ? "Adding..." : "Add"}
                      </button>
                      <button
                        type="button"
                        className="btn-outline btn-sm"
                        disabled={addBusy}
                        onClick={() => {
                          setAdding(null);
                          setPurchasePrice("");
                          setQuantity("1");
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : (
                  <button
                    className="btn-outline btn-sm"
                    onClick={() => setAdding(card.id)}
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
