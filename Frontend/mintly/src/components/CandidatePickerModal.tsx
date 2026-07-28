import { useEffect } from 'react'
import { getCardPrice, type Card } from '../api'
import { money } from '../format'
import CardImage from './CardImage'
import styles from './CandidatePickerModal.module.css'

interface CandidatePickerModalProps {
  // The scan's ranked candidates, best first
  candidates: Card[]
  // Which one is currently chosen for this queued card
  selectedIndex: number
  // Pick a different candidate (also closes the modal)
  onSelect: (index: number) => void
  // Drop this card from the batch and re-capture it
  onRescan: () => void
  // Close without changing the pick
  onClose: () => void
}

// The scanner batch-mode override "popup": shows every candidate the scan
// returned so the user can correct a wrong best-guess, or rescan the card.
// The app's only modal — kept minimal and inside the design tokens.
export default function CandidatePickerModal({
  candidates,
  selectedIndex,
  onSelect,
  onRescan,
  onClose,
}: CandidatePickerModalProps) {
  // Esc closes. Listener only calls props (no synchronous setState), so it's
  // safe inside this effect.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-label="Choose the right card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.header}>
          <h2 className={styles.title}>Not the right card?</h2>
          <button className="btn-outline btn-sm" onClick={onClose} aria-label="Close">
            Close
          </button>
        </div>
        <p className={styles.sub}>Pick the correct match below, or rescan this card.</p>

        <div className={styles.grid}>
          {candidates.map((card, i) => {
            const price = getCardPrice(card)
            const selected = i === selectedIndex
            return (
              <button
                key={card.id}
                type="button"
                className={selected ? `${styles.option} ${styles.optionSelected}` : styles.option}
                onClick={() => onSelect(i)}
                aria-pressed={selected}
              >
                {selected && <span className={styles.currentBadge}>Current pick</span>}
                <CardImage src={card.images.small} alt={card.name} />
                <span className={styles.optionName}>{card.name}</span>
                <span className={styles.optionSet}>
                  {card.set.name}
                  {card.number ? ` · ${card.number}` : ''}
                </span>
                {price != null ? (
                  <span className={styles.optionPrice}>{money(price)}</span>
                ) : card.estimate ? (
                  <span className={styles.optionPrice}>
                    {money(card.estimate.value)} <span className={styles.est}>eBay est.</span>
                  </span>
                ) : null}
              </button>
            )
          })}
        </div>

        <div className={styles.footer}>
          <button className="btn-outline btn-sm" onClick={onRescan}>
            Rescan this card
          </button>
        </div>
      </div>
    </div>
  )
}
