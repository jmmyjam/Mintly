import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  getPortfolio, getCard, getCardPrice, removeCard, updateCard, getToken,
  CONNECTION_ERROR, SessionExpiredError, type Card, type PortfolioCard, type LotCondition,
} from '../api'
import SlabbedCardImage from '../components/SlabbedCardImage'
import DayChange from '../components/DayChange'
import GainLoss from '../components/GainLoss'
import GradingPicker from '../components/GradingPicker'
import PageMessage from '../components/PageMessage'
import PriceHistoryChart, { type PurchaseMarker } from '../components/PriceHistoryChart'
import PriceQtyForm from '../components/PriceQtyForm'
import SignedOutHero from '../components/SignedOutHero'
import StatusMessage from '../components/StatusMessage'
import { useAddCard, useSessionRedirect } from '../hooks'
import { usePortfolios } from '../portfolios'
import { money, signedMoney } from '../format'
import { groupByCard, groupMetrics, formatLotDate, lotISODate, parseUTCDate } from '../portfolio'
import { conditionKey, conditionLabel, isGraded, DEFAULT_GRADING, DEFAULT_GRADE } from '../grading'
import styles from './Holding.module.css'

// The path to one holding — a card scoped to a condition (roadmap #7 Option B).
function holdingPath(cardId: string, g: string): string {
  return `/portfolio/${cardId}?${new URLSearchParams({ g })}`
}

// The portfolio's default order (most recently added first), so prev/next walk
// the same sequence the grid shows — one entry per HOLDING (card + condition).
interface HoldingRef { cardId: string; g: string }

function orderedHoldings(cards: PortfolioCard[]): HoldingRef[] {
  const groups = groupByCard(cards)
  const metrics = new Map(groups.map(g => [g.key, groupMetrics(g)]))
  return groups
    .sort((a, b) => metrics.get(b.key)!.added - metrics.get(a.key)!.added)
    .map(g => ({ cardId: g.card_id, g: conditionKey(g.grading, g.grade) }))
}

// Auth gate + per-holding remount: keying the inner component by card+condition
// resets its state (loading, edit, add) when you page between holdings — no
// synchronous setState in an effect, same trick PriceHistoryChart uses. `g` is
// the condition key (the ?g= param); missing = the unset/raw-unspecified holding.
export default function Holding() {
  const { cardId } = useParams<{ cardId: string }>()
  const [searchParams] = useSearchParams()
  const g = searchParams.get('g') ?? ''
  if (!getToken()) return <SignedOutHero variant="portfolio" />
  if (!cardId) return <PageMessage action={{ to: '/portfolio', label: 'Back to Portfolio' }}><p>Holding not found.</p></PageMessage>
  return <HoldingInner key={`${cardId}::${g}`} cardId={cardId} g={g} />
}

function HoldingInner({ cardId, g }: { cardId: string; g: string }) {
  const navigate = useNavigate()
  const redirectToLogin = useSessionRedirect()
  const [lots, setLots] = useState<PortfolioCard[]>([])
  const [card, setCard] = useState<Card | null>(null)
  const [order, setOrder] = useState<HoldingRef[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editPrice, setEditPrice] = useState('')
  const [editQty, setEditQty] = useState('')
  const [confirmRemoveId, setConfirmRemoveId] = useState<number | null>(null)
  const [lotError, setLotError] = useState<{ id: number; text: string } | null>(null)
  const [adding, setAdding] = useState(false)
  const [addPrice, setAddPrice] = useState('')
  const [addQty, setAddQty] = useState('1')
  const [addCondition, setAddCondition] = useState<LotCondition>({ grading: DEFAULT_GRADING, grade: DEFAULT_GRADE })
  const [editCondition, setEditCondition] = useState<LotCondition>({ grading: DEFAULT_GRADING, grade: DEFAULT_GRADE })
  const { add, busy: addBusy, status: addStatus } = useAddCard()
  // Scope this holding to the active portfolio — you reach it from a portfolio's
  // grid, so the position, purchases, and prev/next pager reflect that portfolio.
  const { activeId } = usePortfolios()

  useEffect(() => {
    let cancelled = false
    getPortfolio(activeId)
      .then(all => {
        if (cancelled) return
        setLots(all.filter(c => c.card_id === cardId && conditionKey(c.grading, c.grade) === g))
        setOrder(orderedHoldings(all))
        return getCard(cardId)
      })
      .then(c => { if (!cancelled && c) setCard(c) })
      .catch(err => {
        if (err instanceof SessionExpiredError) { redirectToLogin(); return }
        if (!cancelled) {
          setError(err instanceof TypeError ? CONNECTION_ERROR : "We couldn't load this holding right now. Please try again in a moment.")
        }
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardId, g, activeId])

  // Left / right arrow keys page between holdings (ignored while typing)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
      const tag = (document.activeElement?.tagName ?? '').toUpperCase()
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      const idx = order.findIndex(h => h.cardId === cardId && h.g === g)
      if (idx === -1) return
      if (e.key === 'ArrowLeft' && idx > 0) navigate(holdingPath(order[idx - 1].cardId, order[idx - 1].g))
      if (e.key === 'ArrowRight' && idx < order.length - 1) navigate(holdingPath(order[idx + 1].cardId, order[idx + 1].g))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [order, cardId, g, navigate])

  function refetchLots() {
    getPortfolio(activeId)
      .then(all => {
        setLots(all.filter(c => c.card_id === cardId && conditionKey(c.grading, c.grade) === g))
        setOrder(orderedHoldings(all))
      })
      .catch(() => {})
  }

  function showLotError(id: number, text: string) {
    setLotError({ id, text })
    setTimeout(() => setLotError(null), 4000)
  }

  async function handleRemove(id: number) {
    setConfirmRemoveId(null)
    try {
      await removeCard(id)
      const next = lots.filter(c => c.id !== id)
      setLots(next)
      if (next.length === 0) navigate('/portfolio')
    } catch (err) {
      if (err instanceof SessionExpiredError) { redirectToLogin(); return }
      showLotError(id, err instanceof TypeError ? CONNECTION_ERROR : "We couldn't remove that lot. Please try again.")
    }
  }

  function startEdit(lot: PortfolioCard) {
    setConfirmRemoveId(null)
    setEditingId(lot.id)
    setEditPrice(String(lot.purchase_price))
    setEditQty(String(lot.quantity))
    // Seed the picker from the lot; an unset legacy lot opens on the Raw default.
    setEditCondition({ grading: lot.grading ?? DEFAULT_GRADING, grade: lot.grade ?? DEFAULT_GRADE })
  }

  async function handleSaveEdit(lot: PortfolioCard) {
    const price = parseFloat(editPrice)
    const qty = parseInt(editQty)
    if (Number.isNaN(price) || price < 0 || Number.isNaN(qty) || qty < 1) {
      showLotError(lot.id, 'Enter a valid price and quantity.')
      return
    }
    try {
      await updateCard(lot.id, {
        purchase_price: price, quantity: qty,
        grading: editCondition.grading, grade: editCondition.grade,
      })
      setEditingId(null)
      // A condition edit can move the lot to a different holding (and flips a
      // graded lot's value to at-cost), so refetch to re-scope + re-price rather
      // than patch locally.
      refetchLots()
    } catch (err) {
      if (err instanceof SessionExpiredError) { redirectToLogin(); return }
      showLotError(lot.id, err instanceof TypeError ? CONNECTION_ERROR : "We couldn't save those changes. Please try again.")
    }
  }

  if (loading) return <PageMessage><p>Loading holding...</p></PageMessage>
  if (error) {
    return (
      <PageMessage action={{ to: '/portfolio', label: 'Back to Portfolio' }}>
        <p className="error">{error}</p>
      </PageMessage>
    )
  }

  const cardName = card?.name ?? lots[0]?.card_name ?? 'This card'

  // The user doesn't own this card (no lots) — a gentle prompt, not a 404
  if (lots.length === 0) {
    return (
      <div className="page">
        <div className={styles.breadcrumb}>
          <Link to="/portfolio" className={styles.crumbLink}>Portfolio</Link>
          <span className={styles.crumbSlash}>/</span>
          <span className={styles.crumbCurrent}>{cardName}</span>
        </div>
        <div className="centered">
          <p>You don't own this card yet.</p>
          <Link to={`/card/${cardId}`} className="btn-primary" style={{ marginTop: '16px' }}>View card &amp; market data</Link>
        </div>
      </div>
    )
  }

  const group = groupByCard(lots)[0]
  const m = groupMetrics(group)
  const single = lots.length === 1
  const market = group.current_price
  const priceChange = group.price_change
  const hasTcg = card ? getCardPrice(card) != null : false
  const sourceLabel = hasTcg ? 'TCGplayer market' : card?.estimate ? 'eBay est.' : 'TCGplayer market'

  const idx = order.findIndex(h => h.cardId === cardId && h.g === g)
  const prev = idx > 0 ? order[idx - 1] : null
  const next = idx >= 0 && idx < order.length - 1 ? order[idx + 1] : null

  const firstLot = lots.reduce((a, b) => (parseUTCDate(a.purchase_date) <= parseUTCDate(b.purchase_date) ? a : b))
  const sortedLots = [...lots].sort((a, b) => parseUTCDate(b.purchase_date).getTime() - parseUTCDate(a.purchase_date).getTime())
  const markers: PurchaseMarker[] = lots.map(l => ({ date: lotISODate(l.purchase_date), price: l.purchase_price }))

  const todayChange = priceChange && m.dayChange != null
    ? { amount: m.dayChange, percent: priceChange.percent, since: priceChange.since }
    : null

  // Where market sits on the paid min->max scale (the cost-basis bar)
  const span = m.maxPaid - m.minPaid
  const fillPct = market != null && span > 0
    ? Math.max(0, Math.min(100, ((market - m.minPaid) / span) * 100))
    : 50
  const marketAboveAvg = market != null && market >= m.avg
  const showBar = !single && market != null

  const numberLine = card
    ? `${card.set.name}${card.number ? ` · #${card.number}${card.set.printedTotal ? `/${card.set.printedTotal}` : ''}` : ''}`
    : ''

  function openAdd() {
    // A new purchase joins THIS holding, so default the picker to its condition
    // (market is null for a graded holding, so the price field starts empty).
    setAddPrice(market != null ? market.toFixed(2) : '')
    setAddQty('1')
    setAddCondition({ grading: group.grading ?? DEFAULT_GRADING, grade: group.grade ?? DEFAULT_GRADE })
    setAdding(true)
  }

  const editForm = (lot: PortfolioCard) => (
    <div className={styles.editStack}>
      <GradingPicker
        variant="full"
        grading={editCondition.grading}
        grade={editCondition.grade}
        onChange={(grading, grade) => setEditCondition({ grading, grade })}
      />
      <PriceQtyForm
        labeled
        smallButtons
        price={editPrice}
        quantity={editQty}
        onPriceChange={setEditPrice}
        onQuantityChange={setEditQty}
        onSubmit={() => handleSaveEdit(lot)}
        submitLabel="Save"
        onCancel={() => setEditingId(null)}
      />
    </div>
  )

  return (
    <div className="page">
      {/* ---- Breadcrumb + prev/next ------------------------------------------ */}
      <div className={styles.breadcrumb}>
        <div className={styles.crumb}>
          <Link to="/portfolio" className={styles.crumbLink}>Portfolio</Link>
          <span className={styles.crumbSlash}>/</span>
          <span className={styles.crumbCurrent}>{cardName}</span>
        </div>
        {order.length > 1 && (
          <div className={styles.nav}>
            <button
              className={styles.navBtn}
              disabled={!prev}
              aria-label="Previous holding"
              onClick={() => prev && navigate(holdingPath(prev.cardId, prev.g))}
            >←</button>
            <span className={`${styles.navCount} num`}>holding {idx + 1} of {order.length}</span>
            <button
              className={styles.navBtn}
              disabled={!next}
              aria-label="Next holding"
              onClick={() => next && navigate(holdingPath(next.cardId, next.g))}
            >→</button>
          </div>
        )}
      </div>

      {/* ---- Two-column body: artwork sidebar + position/purchases ----------- */}
      <div className={styles.body}>
        <div className={styles.sidebar}>
          <span className={styles.media}>
            <SlabbedCardImage src={card?.images?.large ?? group.image_url} alt={cardName} grading={group.grading} grade={group.grade} size="detail" eager />
          </span>
          <Link to={`/card/${cardId}`} className={styles.cardPageLink}>
            Card page &amp; market data <span className={styles.linkArrow}>↗</span>
          </Link>
        </div>

        <div className={styles.main}>
          {/* Title row */}
          <div className={styles.titleRow}>
            <div className={styles.titleLeft}>
              <div className={styles.titleHead}>
                <h1 className={styles.title}>{cardName}</h1>
                <span className={`${styles.ownedPill} num`}>×{m.qty} owned</span>
                {conditionLabel(group.grading, group.grade) && (
                  <span className={styles.conditionChip}>{conditionLabel(group.grading, group.grade)}</span>
                )}
              </div>
              <p className={`${styles.subLine} num`}>
                {numberLine}{numberLine ? ' · ' : ''}{lots.length} {lots.length === 1 ? 'purchase' : 'purchases'} since {formatLotDate(firstLot.purchase_date)}
              </p>
            </div>
            <button className={styles.addBtn} onClick={openAdd}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
                <path d="M12 5v14M5 12h14" />
              </svg>
              Add purchase
            </button>
          </div>

          {/* Position panel */}
          <div className={styles.positionPanel}>
            <div className={styles.statStrip}>
              <div className={styles.statCell}>
                <span className="stat-label">Your value</span>
                <div className={`${styles.statValueBig} num`}>{money(m.value)}</div>
                {todayChange && <DayChange change={todayChange} today />}
              </div>
              <div className={styles.statCell}>
                <span className="stat-label">Cost basis</span>
                <div className={`${styles.statValue} num`}>{money(m.cost)}</div>
                <div className={`${styles.statSub} num`}>avg {money(m.avg)} each</div>
              </div>
              <div className={styles.statCell}>
                <span className="stat-label">Total P&amp;L</span>
                <div className={`${styles.statValue} num ${m.gain != null ? (m.gain >= 0 ? 'positive' : 'negative') : ''}`}>
                  {m.gain != null ? signedMoney(m.gain) : '—'}
                </div>
                {m.gainPct != null && (
                  <div className={`${styles.statSub} num ${m.gain != null && m.gain >= 0 ? 'positive' : 'negative'}`}>
                    {m.gainPct > 0 ? '+' : m.gainPct < 0 ? '−' : ''}{Math.abs(m.gainPct)}%
                  </div>
                )}
              </div>
              <div className={styles.statCell}>
                <span className="stat-label">Market now</span>
                <div className={`${styles.statValue} num`}>{money(market)}</div>
                <div className={styles.statSub}>{sourceLabel}</div>
              </div>
            </div>

            {showBar && (
              <div className={styles.barRow}>
                <div className={`${styles.barLine} num`}>
                  <span>paid {money(m.minPaid)} – {money(m.maxPaid)}</span>
                  <span>break-even at {money(m.avg)} · market {money(market)}</span>
                </div>
                <div className={styles.bar}>
                  <span
                    className={`${styles.barFill} ${marketAboveAvg ? styles.barFillPos : ''}`}
                    style={{ width: `${fillPct}%` }}
                  />
                  <span className={styles.barMarker} style={{ left: `${fillPct}%` }} />
                </div>
              </div>
            )}

            {adding && (
              <div className={styles.addRow}>
                <div className={styles.addHead}>Add a purchase</div>
                {addStatus && addStatus.id === cardId ? (
                  <StatusMessage ok={addStatus.ok}>{addStatus.msg}</StatusMessage>
                ) : (
                  <div className={styles.editStack}>
                    <GradingPicker
                      variant="full"
                      grading={addCondition.grading}
                      grade={addCondition.grade}
                      onChange={(grading, grade) => {
                        if (isGraded(grading) && !isGraded(addCondition.grading)) setAddPrice('')
                        setAddCondition({ grading, grade })
                      }}
                    />
                    <PriceQtyForm
                      labeled
                      price={addPrice}
                      quantity={addQty}
                      onPriceChange={setAddPrice}
                      onQuantityChange={setAddQty}
                      onSubmit={() => add(cardId, addPrice, addQty, activeId, refetchLots, addCondition)}
                      submitLabel="Add purchase"
                      busyLabel="Adding..."
                      busy={addBusy}
                      onCancel={() => setAdding(false)}
                    />
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Purchases table */}
          <div className={styles.purchases}>
            <div className={styles.pHead}>
              <span className={styles.pTitle}>Purchases</span>
              <span className={styles.pSub}>Newest first</span>
            </div>
            <div className={styles.tableScroll}>
              <div className={styles.table}>
                <div className={styles.colLabels}>
                  <span>Purchased</span><span>Qty</span><span>Paid each</span><span>Cost</span><span>P&amp;L</span><span />
                </div>
                <div className={styles.rows}>
                  {sortedLots.map(lot => (
                    <div key={lot.id}>
                      {editingId === lot.id ? (
                        <div className={styles.editRow}>
                          <span className={styles.editDate}>{formatLotDate(lot.purchase_date)}</span>
                          {editForm(lot)}
                        </div>
                      ) : (
                        <div className={`${styles.row} num`}>
                          <span className={styles.rowDate}>{formatLotDate(lot.purchase_date)}</span>
                          <span>{lot.quantity}</span>
                          <span>{money(lot.purchase_price)}</span>
                          <span>{money(lot.purchase_price * lot.quantity)}</span>
                          <span>{lot.gain_loss != null ? <GainLoss value={lot.gain_loss} pct={lot.gain_loss_pct} /> : '—'}</span>
                          {confirmRemoveId === lot.id ? (
                            <span className={styles.cellActions}>
                              <button className={`${styles.actionBtn} ${styles.actionRemove}`} onClick={() => handleRemove(lot.id)}>Confirm</button>
                              <button className={styles.actionBtn} onClick={() => setConfirmRemoveId(null)}>Cancel</button>
                            </span>
                          ) : (
                            <span className={styles.cellActions}>
                              <button className={styles.actionBtn} onClick={() => startEdit(lot)}>Edit</button>
                              <button className={`${styles.actionBtn} ${styles.actionRemove}`} onClick={() => setConfirmRemoveId(lot.id)}>Remove</button>
                            </span>
                          )}
                        </div>
                      )}
                      {lotError?.id === lot.id && <StatusMessage ok={false}>{lotError.text}</StatusMessage>}
                    </div>
                  ))}
                </div>
                <div className={`${styles.totals} num`}>
                  <span className={styles.totalsMuted}>Total</span>
                  <span>{m.qty}</span>
                  <span className={styles.totalsMuted}>avg {money(m.avg)}</span>
                  <span>{money(m.cost)}</span>
                  <span>{m.gain != null ? <GainLoss value={m.gain} /> : '—'}</span>
                  <span />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ---- Market vs. cost chart, full width ------------------------------- */}
      <div className={styles.chartWrap}>
        <PriceHistoryChart
          cardId={cardId}
          title="Market price vs. your cost"
          segmentedRange
          currentPrice={market}
          avgCost={m.avg}
          purchases={markers}
        />
      </div>
    </div>
  )
}
