import { useState } from 'react'
import { GRADING_TYPES, gradeOptions, isGraded, conditionLabel } from '../grading'
import styles from './GradingPicker.module.css'

// The two-field condition/grade chooser (roadmap #7): a grading-type select whose
// value select switches vocabulary — TCGplayer conditions for Raw, the grader's
// grades otherwise, free text for Other. The parent owns the (grading, grade)
// state. Controls are styled like the price/qty inputs they sit beside so the add
// form reads as one set.
interface GradingPickerProps {
  grading: string | null
  grade: string | null
  onChange: (grading: string | null, grade: string | null) => void
  // 'full' = both selects always visible (roomy vertical forms — CardDetail,
  // Holding editor); 'compact' = a collapsed one-line chip that expands (dense
  // grids + horizontal action bars — Search tile, Scan).
  variant?: 'full' | 'compact'
  // Extra class on the root, for a caller to control its flex sizing in a row
  // (e.g. a full-width own-line in Scan's wrapping best-guess action bar).
  className?: string
}

export default function GradingPicker({ grading, grade, onChange, variant = 'full', className }: GradingPickerProps) {
  const [open, setOpen] = useState(false)
  const activeGrading = grading ?? 'Raw'
  const options = gradeOptions(activeGrading)
  const isOther = activeGrading === 'Other'

  function changeGrading(next: string) {
    // Reset the value to the first option of the new type (blank for Other's free text)
    const opts = gradeOptions(next)
    onChange(next, next === 'Other' ? '' : (opts[0] ?? null))
  }

  const controls = (
    <div className={styles.controls}>
      <label className={styles.field}>
        <span className="stat-label">Grading</span>
        <select
          className="mini-input"
          value={activeGrading}
          onChange={e => changeGrading(e.target.value)}
        >
          {GRADING_TYPES.map(g => (
            <option key={g} value={g}>{g === 'Raw' ? 'Raw (ungraded)' : g}</option>
          ))}
        </select>
      </label>
      <label className={styles.field}>
        <span className="stat-label">{isGraded(activeGrading) ? 'Grade' : 'Condition'}</span>
        {isOther ? (
          <input
            className="mini-input"
            type="text"
            maxLength={24}
            placeholder="e.g. TAG 10"
            value={grade ?? ''}
            onChange={e => onChange('Other', e.target.value)}
          />
        ) : (
          <select
            className="mini-input"
            value={grade ?? options[0] ?? ''}
            onChange={e => onChange(activeGrading, e.target.value)}
          >
            {options.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
        )}
      </label>
    </div>
  )

  const rootClass = [styles.picker, variant === 'compact' && styles.compact, className]
    .filter(Boolean)
    .join(' ')

  if (variant === 'full') return <div className={rootClass}>{controls}</div>

  // Compact: a collapsed one-line chip (styled like the price input) that expands
  // into the two selects, so a dense tile or action bar stays clean while the
  // default (Raw / Near Mint) still adds.
  return (
    <div className={rootClass}>
      {open ? controls : (
        <button type="button" className={styles.summary} onClick={() => setOpen(true)} aria-label={`Condition: ${conditionLabel(activeGrading, grade) || 'Raw'}. Change`}>
          <span className={styles.summaryText}>{conditionLabel(activeGrading, grade) || 'Raw'}</span>
          <svg className={styles.summaryChevron} viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
      )}
    </div>
  )
}
