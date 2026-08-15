import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  scanCard,
  addCardBatch,
  getCardPrice,
  getToken,
  errorMessage,
  reportScanFeedback,
  SessionExpiredError,
  type Card,
  type ScanFeedbackEvent,
  type ScanOutcome,
} from "../api";
import CameraViewfinder from "../components/CameraViewfinder";
import CardImage from "../components/CardImage";
import CandidatePickerModal from "../components/CandidatePickerModal";
import DayChange from "../components/DayChange";
import PriceQtyForm from "../components/PriceQtyForm";
import PortfolioPicker from "../components/PortfolioPicker";
import GradingPicker from "../components/GradingPicker";
import { DEFAULT_GRADING, DEFAULT_GRADE, isGraded } from "../grading";
import type { LotCondition } from "../api";
import SignedOutHero from "../components/SignedOutHero";
import StatusMessage from "../components/StatusMessage";
import { useAddCard, useSessionRedirect } from "../hooks";
import { usePortfolios } from "../portfolios";
import { money } from "../format";
import styles from "./Scan.module.css";

// CLIP cosine similarity below this marks a best-guess as shaky ("Check this")
// in batch mode. Good matches observed roughly 0.8-0.95; tune against real
// captures. A card scanned before the embedding backfill has no score and is
// never flagged.
const SCAN_CONFIDENCE_FLOOR = 0.85;

// One scanned card waiting in the batch queue: the photo, the ranked candidates
// the scan returned, which one is currently chosen, and the price/qty to add it at.
interface QueueItem {
  key: string;
  thumbnail: string;
  candidates: Card[];
  selectedIndex: number;
  price: string;
  quantity: string;
  failed?: boolean; // set when a commit couldn't add this one, so its row stands out
}

// The market price (or eBay estimate) to pre-fill a queued card's price with —
// same order the single-add form uses, so the value shown is the value added.
function defaultPriceFor(card: Card): string {
  const price = getCardPrice(card);
  if (price != null) return price.toFixed(2);
  if (card.estimate) return card.estimate.value.toFixed(2);
  return "";
}

// Build an anonymous scanner-accuracy event (roadmap #10) from a scan's ranked
// candidates and the index the user confirmed. picked_rank 0 = the top guess was
// right; a higher rank means the top guess was wrong and the truth ranked lower.
function confirmEvent(candidates: Card[], pickedIndex: number): ScanFeedbackEvent {
  const picked = candidates[pickedIndex];
  const top = candidates[0];
  return {
    outcome: "confirmed",
    candidate_count: candidates.length,
    picked_rank: pickedIndex,
    picked_score: picked?.matchScore ?? null,
    top_score: top?.matchScore ?? null,
    top_card_id: top?.id ?? null,
    picked_card_id: picked?.id ?? null,
  };
}

// A "none of these were right" gesture (searched away / rescanned) — no pick, so
// only the top candidate is recorded. Corrects the survivorship bias in the
// confirm-only signal (give-up scans would otherwise be invisible).
function missEvent(candidates: Card[], outcome: ScanOutcome): ScanFeedbackEvent {
  const top = candidates[0];
  return {
    outcome,
    candidate_count: candidates.length,
    top_score: top?.matchScore ?? null,
    top_card_id: top?.id ?? null,
  };
}

const PlusIcon = () => (
  <svg
    viewBox="0 0 24 24"
    width="14"
    height="14"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.2"
    strokeLinecap="round"
    aria-hidden="true"
  >
    <path d="M12 5v14M5 12h14" />
  </svg>
);

const CameraIcon = () => (
  <svg
    viewBox="0 0 24 24"
    width="16"
    height="16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.9"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <rect x="3" y="6" width="18" height="13" rx="2.5" />
    <circle cx="12" cy="12.5" r="3.4" />
  </svg>
);

const AlertIcon = () => (
  <svg
    viewBox="0 0 24 24"
    width="17"
    height="17"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.9"
    strokeLinecap="round"
    style={{ flex: "none" }}
    aria-hidden="true"
  >
    <path d="M12 8.5v5M12 16.6v.4" />
    <circle cx="12" cy="12" r="8.5" />
  </svg>
);

const ArrowIcon = () => (
  <svg
    viewBox="0 0 24 24"
    width="14"
    height="14"
    fill="none"
    strokeWidth="2"
    strokeLinecap="round"
    style={{ stroke: "var(--slash)", flex: "none" }}
    aria-hidden="true"
  >
    <path d="M7 12h10M13 8l4 4-4 4" />
  </svg>
);

export default function Scan() {
  const navigate = useNavigate();
  const redirectToLogin = useSessionRedirect();
  const [batchMode, setBatchMode] = useState(false);
  const [captured, setCaptured] = useState<string | null>(null); // thumbnail data URL
  const [matching, setMatching] = useState(false); // upload + match in flight
  const [results, setResults] = useState<Card[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [manualQuery, setManualQuery] = useState("");

  // Shared add-to-portfolio flow (single mode), same as Search/CardDetail
  const { add, busy: addBusy, status: addStatus } = useAddCard();
  // Which portfolio scanned cards go to (defaults to the active one). Batch add
  // can also create a new one inline via the picker's allowCreate.
  const { activeId } = usePortfolios();
  const [batchTarget, setBatchTarget] = useState<number | null>(null);
  const [singleTarget, setSingleTarget] = useState<number | null>(null);
  // Single-mode best-guess add (its price/qty row is always visible)
  const [bestPrice, setBestPrice] = useState("");
  const [bestQty, setBestQty] = useState("1");
  // Single-mode "other matches" inline add (one open at a time)
  const [adding, setAdding] = useState<string | null>(null);
  const [purchasePrice, setPurchasePrice] = useState("");
  const [quantity, setQuantity] = useState("1");
  // Condition/grade for the single-mode adds (best guess + other matches).
  const [singleCondition, setSingleCondition] = useState<LotCondition>({ grading: DEFAULT_GRADING, grade: DEFAULT_GRADE });
  const [otherCondition, setOtherCondition] = useState<LotCondition>({ grading: DEFAULT_GRADING, grade: DEFAULT_GRADE });
  // At most one accuracy label per single-mode capture (roadmap #10): the first
  // confirm, or the searched-away miss. Reset on each new capture / reset().
  const scanReported = useRef(false);

  // Batch mode
  const [queue, setQueue] = useState<QueueItem[]>([]);
  // One condition applied to the whole batch (scan stacks are usually one kind).
  const [batchCondition, setBatchCondition] = useState<LotCondition>({ grading: DEFAULT_GRADING, grade: DEFAULT_GRADE });
  const [overrideKey, setOverrideKey] = useState<string | null>(null);
  const [committing, setCommitting] = useState(false);
  const [batchStatus, setBatchStatus] = useState<{
    msg: string;
    ok: boolean;
  } | null>(null);
  const [lastAdded, setLastAdded] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false); // leave-batch confirm
  const [confirmClearAll, setConfirmClearAll] = useState(false); // clear-queue confirm

  function handleCapture(canvas: HTMLCanvasElement) {
    const thumb = canvas.toDataURL("image/jpeg", 0.85);

    if (batchMode) {
      setNotice(null);
      setMatching(true);
      canvas.toBlob(
        (blob) => {
          if (!blob) {
            setMatching(false);
            setNotice("Couldn't read the capture. Try again.");
            return;
          }
          scanCard(blob)
            .then((page) => {
              if (page.data.length === 0) {
                setNotice(
                  "No match for that one. Line the card up and scan it again.",
                );
                return;
              }
              const best = page.data[0];
              // Newest scan goes to the top of the queue so it's the first thing
              // you review without scrolling.
              setQueue((q) => [
                {
                  key: `${Date.now()}-${q.length}`,
                  thumbnail: thumb,
                  candidates: page.data,
                  selectedIndex: 0,
                  price: defaultPriceFor(best),
                  quantity: "1",
                },
                ...q,
              ]);
              setLastAdded(best.name);
              setTimeout(() => setLastAdded(null), 2500);
            })
            .catch((err) => {
              if (err instanceof SessionExpiredError) {
                redirectToLogin();
                return;
              }
              setNotice("Something went wrong scanning. Please try again.");
            })
            .finally(() => setMatching(false));
        },
        "image/jpeg",
        0.85,
      );
      return;
    }

    // Single mode
    setCaptured(thumb);
    setResults(null);
    setNotice(null);
    setMatching(true);
    scanReported.current = false; // a fresh capture is a fresh, unreported scan
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          setMatching(false);
          setNotice("Couldn't read the capture. Try again.");
          return;
        }
        scanCard(blob)
          .then((page) => {
            setResults(page.data);
            if (page.data.length === 0) {
              setNotice(
                "No match found. Try scanning again, or search by name.",
              );
            } else {
              // Seed the always-visible add row from the best guess's market price
              setBestPrice(defaultPriceFor(page.data[0]));
              setBestQty("1");
            }
          })
          .catch((err) => {
            if (err instanceof SessionExpiredError) {
              redirectToLogin();
              return;
            }
            setResults([]);
            setNotice("Something went wrong scanning. Please try again.");
          })
          .finally(() => setMatching(false));
      },
      "image/jpeg",
      0.85,
    );
  }

  function reset() {
    setCaptured(null);
    setResults(null);
    setNotice(null);
    setAdding(null);
    setPurchasePrice("");
    setQuantity("1");
    setBestPrice("");
    setBestQty("1");
    scanReported.current = false;
  }

  // Log which candidate the user confirmed (single mode), at most once per
  // capture — the accuracy signal is one truth per scanned card.
  function reportConfirmPick(pickedIndex: number) {
    if (!results || pickedIndex < 0 || scanReported.current) return;
    scanReported.current = true;
    reportScanFeedback([confirmEvent(results, pickedIndex)]);
  }

  function pickSingleCondition(grading: string | null, grade: string | null) {
    if (isGraded(grading) && !isGraded(singleCondition.grading)) setBestPrice("");
    setSingleCondition({ grading, grade });
  }

  function pickOtherCondition(grading: string | null, grade: string | null) {
    if (isGraded(grading) && !isGraded(otherCondition.grading)) setPurchasePrice("");
    setOtherCondition({ grading, grade });
  }

  function handleAdd(card: Card) {
    add(card.id, purchasePrice, quantity, singleTarget ?? activeId, () => {
      // The alt tile's rank is its position in the full results list.
      reportConfirmPick(results ? results.findIndex((c) => c.id === card.id) : -1);
      setAdding(null);
      setPurchasePrice("");
      setQuantity("1");
    }, otherCondition);
  }

  function manualSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = manualQuery.trim();
    if (!q) return;
    // "Not it? Search by name" after a scan is an explicit miss — the top-12
    // didn't contain the card. Only counts if nothing was confirmed first.
    if (results && results.length > 0 && !scanReported.current) {
      scanReported.current = true;
      reportScanFeedback([missEvent(results, "searched_away")]);
    }
    navigate(`/search?q=${encodeURIComponent(q)}`);
  }

  // ----- Batch helpers -------------------------------------------------------

  function doSwitch(toBatch: boolean) {
    setBatchMode(toBatch);
    setConfirmClear(false);
    setConfirmClearAll(false);
    reset();
    setQueue([]);
    setBatchStatus(null);
    setOverrideKey(null);
    setLastAdded(null);
  }

  function switchMode(toBatch: boolean) {
    if (toBatch === batchMode) return;
    // Leaving batch with a pending queue: two-step inline confirm (no native confirm())
    if (!toBatch && queue.length > 0) {
      setConfirmClear(true);
      return;
    }
    doSwitch(toBatch);
  }

  function updateItem(key: string, patch: Partial<QueueItem>) {
    // Any edit to a row clears its failed flag — the user is acting on it.
    setQueue((q) =>
      q.map((it) => (it.key === key ? { ...it, ...patch, failed: false } : it)),
    );
  }

  function removeItem(key: string) {
    setQueue((q) => q.filter((it) => it.key !== key));
    if (overrideKey === key) setOverrideKey(null);
  }

  function clearQueue() {
    setQueue([]);
    setBatchStatus(null);
    setConfirmClearAll(false);
  }

  // Override modal picked a different candidate: switch to it and re-seed the
  // price from the newly chosen card (the old price was for the wrong card).
  function chooseCandidate(index: number) {
    if (!overrideKey) return;
    setQueue((q) =>
      q.map((it) =>
        it.key === overrideKey
          ? {
              ...it,
              selectedIndex: index,
              price: defaultPriceFor(it.candidates[index]),
              failed: false,
            }
          : it,
      ),
    );
    setOverrideKey(null);
  }

  async function commitBatch() {
    if (!queue.length || committing) return;
    setCommitting(true);
    setBatchStatus(null);
    try {
      const items = queue.map((it) => {
        const card = it.candidates[it.selectedIndex];
        const price = parseFloat(it.price);
        return {
          card_id: card.id,
          purchase_price: Number.isNaN(price) ? null : price,
          quantity: parseInt(it.quantity, 10) || 1,
          grading: batchCondition.grading,
          grade: batchCondition.grade,
        };
      });
      const result = await addCardBatch(items, batchTarget ?? activeId);
      const failedIds = new Set(result.failed.map((f) => f.card_id));
      // Report the confirmed pick for every card that actually landed (roadmap
      // #10). Reporting only the succeeded ones dedupes cleanly: a failed row
      // stays in the queue and is reported when a later retry succeeds.
      reportScanFeedback(
        queue
          .filter((it) => !failedIds.has(it.candidates[it.selectedIndex].id))
          .map((it) => confirmEvent(it.candidates, it.selectedIndex)),
      );
      if (result.failed.length === 0) {
        setBatchStatus({ msg: result.message, ok: true });
        setQueue([]);
      } else {
        // Keep the cards that couldn't be added so they can be fixed and retried
        setQueue((q) =>
          q
            .filter((it) => failedIds.has(it.candidates[it.selectedIndex].id))
            .map((it) => ({ ...it, failed: true })),
        );
        setBatchStatus({
          msg: `Added ${result.added}. ${result.failed.length} couldn't be added and are still listed below.`,
          ok: result.added > 0,
        });
      }
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        redirectToLogin();
        return;
      }
      setBatchStatus({
        msg: errorMessage(
          err,
          "We couldn't add those cards. Please try again.",
        ),
        ok: false,
      });
    } finally {
      setCommitting(false);
    }
  }

  // Derived batch figures
  const batchTotal = queue.reduce(
    (sum, it) =>
      sum + (parseFloat(it.price) || 0) * (parseInt(it.quantity, 10) || 1),
    0,
  );
  const shakyCount = queue.filter((it) => {
    const s = it.candidates[it.selectedIndex].matchScore;
    return s != null && s < SCAN_CONFIDENCE_FLOOR;
  }).length;

  // ----- Single-mode "other matches" tile ------------------------------------

  function renderAltTile(card: Card) {
    const price = getCardPrice(card);
    const est = price == null ? (card.estimate?.value ?? null) : null;
    const pct =
      card.matchScore != null ? Math.round(card.matchScore * 100) : null;
    const isAdding = adding === card.id;
    const status = addStatus?.id === card.id ? addStatus : null;

    return (
      <div key={card.id} className={styles.altTile}>
        <Link to={`/card/${card.id}`} className={styles.altLink}>
          <span className={styles.altArt}>
            <CardImage src={card.images.small} alt={card.name} />
            {pct != null && (
              <span className={`${styles.altPct} num`}>{pct}%</span>
            )}
          </span>
          <div>
            <p className={styles.altName}>{card.name}</p>
            <p className={styles.altMeta}>
              {card.set.name}
              {card.number ? ` · #${card.number}` : ""}
            </p>
          </div>
          <div className={`${styles.altPrice} num`}>
            {price != null ? (
              money(price)
            ) : est != null ? (
              <>
                {money(est)} <span className={styles.estLabel}>eBay est.</span>
              </>
            ) : (
              <span className={styles.priceNone}>—</span>
            )}
          </div>
        </Link>

        {status ? (
          <StatusMessage ok={status.ok}>{status.msg}</StatusMessage>
        ) : isAdding ? (
          <>
            <GradingPicker
              variant="compact"
              grading={otherCondition.grading}
              grade={otherCondition.grade}
              onChange={pickOtherCondition}
            />
            <PriceQtyForm
              className={styles.altAddForm}
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
          </>
        ) : (
          <button
            className={styles.altBtn}
            onClick={() => {
              setAdding(card.id);
              setOtherCondition({ grading: DEFAULT_GRADING, grade: DEFAULT_GRADE });
              if (price == null && est != null)
                setPurchasePrice(est.toFixed(2));
            }}
          >
            <PlusIcon /> Portfolio
          </button>
        )}
      </div>
    );
  }

  // ----- Batch-mode queue row ------------------------------------------------

  function renderQueueRow(item: QueueItem) {
    const card = item.candidates[item.selectedIndex];
    const score = card.matchScore;
    const shaky = score != null && score < SCAN_CONFIDENCE_FLOOR;
    const pct = score != null ? Math.round(score * 100) : null;

    const rowClass = [
      styles.queueRow,
      shaky ? styles.queueRowShaky : "",
      item.failed ? styles.queueRowFailed : "",
    ]
      .filter(Boolean)
      .join(" ");

    return (
      <li key={item.key} className={rowClass}>
        <div className={styles.pair}>
          <img
            src={item.thumbnail}
            alt="Your scan"
            className={styles.captureThumb}
          />
          <ArrowIcon />
          <div className={styles.matchArt}>
            <CardImage src={card.images.small} alt={card.name} />
          </div>
        </div>

        <div className={styles.rowInfo}>
          <div className={styles.rowNameLine}>
            <Link to={`/card/${card.id}`} className={styles.rowName}>
              {card.name}
            </Link>
            {pct != null &&
              (shaky ? (
                <span className={`${styles.badgeShaky} num`}>
                  Check this · {pct}%
                </span>
              ) : (
                <span className={`${styles.badgeOk} num`}>{pct}% match</span>
              ))}
          </div>
          <p className={`${styles.rowMeta} num`}>
            {card.set.name}
            {card.number ? ` · #${card.number}` : ""}
          </p>
        </div>

        <div className={styles.rowControls}>
          <input
            type="number"
            className={`${styles.priceInput} num`}
            placeholder="Price"
            aria-label={`Price paid for ${card.name}`}
            min="0"
            step="0.01"
            value={item.price}
            onChange={(e) => updateItem(item.key, { price: e.target.value })}
          />
          <input
            type="number"
            className={`${styles.qtyInput} num`}
            placeholder="Qty"
            aria-label={`Quantity of ${card.name}`}
            min="1"
            value={item.quantity}
            onChange={(e) => updateItem(item.key, { quantity: e.target.value })}
          />
          <button
            className={`${styles.changeBtn} ${shaky ? styles.changeShaky : ""}`}
            onClick={() => setOverrideKey(item.key)}
          >
            Change
          </button>
          <button
            type="button"
            className={styles.removeBtn}
            aria-label={`Remove ${card.name}`}
            onClick={() => removeItem(item.key)}
          >
            ✕
          </button>
        </div>
      </li>
    );
  }

  if (!getToken()) {
    return <SignedOutHero variant="scan" />;
  }

  const overrideItem = queue.find((it) => it.key === overrideKey) || null;
  const best = results && results.length > 0 ? results[0] : null;
  const alternates = results ? results.slice(1) : [];
  const bestPct =
    best?.matchScore != null ? Math.round(best.matchScore * 100) : null;
  const bestMarket = best ? getCardPrice(best) : null;
  const bestStatus = best && addStatus?.id === best.id ? addStatus : null;

  return (
    <div className="page">
      <div className={styles.pageHead}>
        <div className={styles.headText}>
          <h1 className={styles.title}>Scan a card</h1>
          {batchMode ? (
            <p className={styles.intro}>
              Fill the frame with one card and hold steady. Each scan drops into
              the batch, and nothing is added to your portfolio until you review
              it.
            </p>
          ) : !captured ? (
            <p className={styles.intro}>
              Point your camera at a Pokémon card and line it up inside the
              frame. Mintly matches the photo against its card database to find
              it, then you can add it to your portfolio.
            </p>
          ) : null}
        </div>
        <div
          className={`segmented segmented-lg ${styles.modeToggle}`}
          role="group"
          aria-label="Scan mode"
        >
          <button
            className={`segmented-item ${!batchMode ? "is-selected" : ""}`}
            aria-pressed={!batchMode}
            onClick={() => switchMode(false)}
          >
            Single
          </button>
          <button
            className={`segmented-item ${batchMode ? "is-selected" : ""}`}
            aria-pressed={batchMode}
            onClick={() => switchMode(true)}
          >
            Batch add
          </button>
        </div>
      </div>

      {confirmClear && (
        <div className={styles.confirmClear}>
          <span>
            Switch to single scan? Your {queue.length} scanned{" "}
            {queue.length === 1 ? "card" : "cards"} will be discarded.
          </span>
          <div className={styles.confirmButtons}>
            <button
              className="btn-outline btn-sm"
              onClick={() => doSwitch(false)}
            >
              Discard and switch
            </button>
            <button
              className="btn-primary btn-sm"
              onClick={() => setConfirmClear(false)}
            >
              Keep scanning
            </button>
          </div>
        </div>
      )}

      {batchMode ? (
        // ----- Batch mode: camera left, live queue right -----
        <div className={styles.batchBody}>
          <div className={styles.cameraCol}>
            <CameraViewfinder
              onCapture={handleCapture}
              busy={matching}
              onSearchByName={() => navigate("/search")}
            />
            <div className={styles.statusLine}>
              {!matching && lastAdded && (
                <span className={styles.added}>
                  ✓ Added {lastAdded} to the batch
                </span>
              )}
              {!matching && !lastAdded && notice && (
                <span className="prices-note">{notice}</span>
              )}
            </div>
            <p className={styles.tips}>
              For the best match: fill the frame with the card, hold steady so
              it&apos;s in focus, and use good, even light.
            </p>
          </div>

          <div className={styles.queueCol}>
            <div className={styles.queueHead}>
              <div className={styles.queueTitleWrap}>
                <span className={styles.queueTitle}>Batch</span>
                {queue.length > 0 && (
                  <span className={`${styles.countPill} num`}>
                    {queue.length} {queue.length === 1 ? "card" : "cards"} ·{" "}
                    {money(batchTotal)}
                  </span>
                )}
              </div>
              <div className={styles.queueActions}>
                <PortfolioPicker
                  value={batchTarget}
                  onChange={setBatchTarget}
                  allowCreate
                  label="Add to"
                  ariaLabel="Add batch to portfolio"
                />
                {queue.length > 0 &&
                  (confirmClearAll ? (
                    <span className={styles.clearConfirm}>
                      Clear all?
                      <button className={styles.clearYes} onClick={clearQueue}>
                        Yes
                      </button>
                      <button
                        className={styles.clearNo}
                        onClick={() => setConfirmClearAll(false)}
                      >
                        No
                      </button>
                    </span>
                  ) : (
                    <button
                      className={styles.clearAll}
                      onClick={() => setConfirmClearAll(true)}
                    >
                      Clear all
                    </button>
                  ))}
                <button
                  className="btn-primary"
                  disabled={queue.length === 0 || committing}
                  onClick={commitBatch}
                >
                  {committing
                    ? "Adding…"
                    : `Add all${queue.length > 0 ? ` ${queue.length}` : ""} to portfolio`}
                </button>
              </div>
            </div>

            <div className={styles.batchCondition}>
              <span className="stat-label">Condition applied to all</span>
              <GradingPicker
                variant="compact"
                grading={batchCondition.grading}
                grade={batchCondition.grade}
                onChange={(grading, grade) => setBatchCondition({ grading, grade })}
              />
            </div>

            {batchStatus && (
              <StatusMessage ok={batchStatus.ok}>
                {batchStatus.msg}
              </StatusMessage>
            )}

            {shakyCount > 0 && (
              <div className={styles.warnBanner}>
                <AlertIcon />
                <span>
                  {shakyCount === 1
                    ? "1 card needs a look, its match wasn't confident."
                    : `${shakyCount} cards need a look, their matches weren't confident.`}
                </span>
              </div>
            )}

            {queue.length === 0 ? (
              <div className={styles.emptyQueue}>
                Scanned cards collect here. Nothing is added until you tap Add
                all.
              </div>
            ) : (
              <>
                <ul className={styles.queue}>{queue.map(renderQueueRow)}</ul>
                <p className={styles.footerNote}>
                  Prices pre-fill from the market value. Edit any of them before
                  adding. Nothing is saved until you tap Add all.
                </p>
              </>
            )}
          </div>
        </div>
      ) : !captured ? (
        // ----- Single mode, before a capture: centered camera -----
        <div className={styles.singleCamera}>
          <CameraViewfinder
            onCapture={handleCapture}
            busy={matching}
            onSearchByName={() => navigate("/search")}
          />
          <p className={styles.tips}>
            For the best match: fill the frame with the card, hold steady so
            it&apos;s in focus, and use good, even light.
          </p>
        </div>
      ) : (
        // ----- Single mode, after a capture: capture + best guess + alternates -----
        <div className={styles.singleResult}>
          <div className={styles.captureCol}>
            <span className={styles.captureLabel}>Your capture</span>
            <img
              src={captured}
              alt="Your captured card"
              className={styles.capturePhoto}
            />
            <button className={styles.scanAnother} onClick={reset}>
              <CameraIcon /> Scan another
            </button>
            <form onSubmit={manualSearch}>
              <input
                className={styles.manualInput}
                value={manualQuery}
                onChange={(e) => setManualQuery(e.target.value)}
                placeholder="Not it? Search by name"
                aria-label="Search by card name"
              />
            </form>
          </div>

          <div className={styles.resultCol}>
            {matching && <p className={styles.status}>Finding your card…</p>}
            {notice && <p className="prices-note">{notice}</p>}

            {best && (
              <div className={styles.bestBlock}>
                <div className={styles.bestHead}>
                  <h2 className={styles.bestHeading}>We think this is…</h2>
                  {bestPct != null && (
                    <span className={`${styles.badgeOk} num`}>
                      {bestPct}% match
                    </span>
                  )}
                </div>
                <div className={styles.bestCard}>
                  <Link to={`/card/${best.id}`} className={styles.bestArt}>
                    <CardImage src={best.images.small} alt={best.name} />
                  </Link>
                  <div className={styles.bestInfo}>
                    <div>
                      <p className={styles.bestName}>{best.name}</p>
                      <p className={styles.bestMeta}>
                        {best.set.name}
                        {best.number ? ` · #${best.number}` : ""}
                        {best.rarity ? ` · ${best.rarity}` : ""}
                      </p>
                    </div>
                    <div className={`${styles.bestPriceRow} num`}>
                      {bestMarket != null ? (
                        <>
                          <span className={styles.bestPrice}>
                            {money(bestMarket)}
                          </span>
                          {best.priceChange && (
                            <DayChange change={best.priceChange} today />
                          )}
                        </>
                      ) : best.estimate ? (
                        <span className={styles.bestPrice}>
                          {money(best.estimate.value)}{" "}
                          <span className={styles.estLabel}>eBay est.</span>
                        </span>
                      ) : (
                        <span className={styles.bestPrice}>—</span>
                      )}
                    </div>

                    {bestStatus ? (
                      <StatusMessage ok={bestStatus.ok}>
                        {bestStatus.msg}
                      </StatusMessage>
                    ) : (
                      <div className={styles.bestActions}>
                        <PortfolioPicker
                          value={singleTarget}
                          onChange={setSingleTarget}
                          label="Add to"
                          className={styles.bestPortfolio}
                        />
                        <GradingPicker
                          variant="full"
                          className={styles.bestGrading}
                          grading={singleCondition.grading}
                          grade={singleCondition.grade}
                          onChange={pickSingleCondition}
                        />
                        <input
                          type="number"
                          className={`${styles.bestPriceInput} num`}
                          placeholder="Price paid"
                          aria-label="Price paid"
                          min="0"
                          step="0.01"
                          value={bestPrice}
                          onChange={(e) => setBestPrice(e.target.value)}
                        />
                        <input
                          type="number"
                          className={`${styles.bestQtyInput} num`}
                          placeholder="Qty"
                          aria-label="Quantity"
                          min="1"
                          value={bestQty}
                          onChange={(e) => setBestQty(e.target.value)}
                        />
                        <button
                          className={styles.bestAdd}
                          disabled={addBusy}
                          onClick={() =>
                            add(
                              best.id,
                              bestPrice,
                              bestQty,
                              singleTarget ?? activeId,
                              () => reportConfirmPick(0),
                              singleCondition,
                            )
                          }
                        >
                          {addBusy ? "Adding…" : "Add to portfolio"}
                        </button>
                        <Link
                          to={`/card/${best.id}`}
                          className={styles.cardPageLink}
                        >
                          Card page ↗
                        </Link>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {alternates.length > 0 && (
              <div>
                <h3 className={styles.otherHeading}>Other matches</h3>
                <div className={styles.altGrid}>
                  {alternates.map(renderAltTile)}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {overrideItem && (
        <CandidatePickerModal
          candidates={overrideItem.candidates}
          selectedIndex={overrideItem.selectedIndex}
          onSelect={chooseCandidate}
          onRescan={() => {
            // Rejecting every candidate is an explicit miss for this scan.
            reportScanFeedback([missEvent(overrideItem.candidates, "rescanned")]);
            removeItem(overrideItem.key);
          }}
          onClose={() => setOverrideKey(null)}
        />
      )}
    </div>
  );
}
