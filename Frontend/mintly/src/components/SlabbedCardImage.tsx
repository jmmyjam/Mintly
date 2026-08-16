import CardImage from './CardImage'
import { isGraded } from '../grading'
import styles from './SlabbedCardImage.module.css'

// Card artwork that reads as a graded slab in the portfolio (roadmap #7). For a
// graded lot it wraps CardImage in a fake grading case styled to look like a card
// photographed inside a real slab: a beveled clear-plastic shell with a glossy
// reflection, a cream paper label carrying the grader + grade as REAL text
// (identity never rides on color alone), and the card recessed into a plastic
// well. A raw/unset lot renders the bare CardImage, unchanged.
interface SlabbedCardImageProps {
  src?: string | null
  alt: string
  grading: string | null
  grade: string | null
  size?: 'tile' | 'detail'
  eager?: boolean
}

export default function SlabbedCardImage({ src, alt, grading, grade, size = 'tile', eager = false }: SlabbedCardImageProps) {
  if (!isGraded(grading)) {
    return <CardImage src={src} alt={alt} size={size} eager={eager} />
  }
  const label = `${grading}${grade ? ` ${grade}` : ''}`
  return (
    <span className={`${styles.slab} ${size === 'detail' ? styles.detail : styles.tile}`}>
      {/* Paper label seen through the plastic: grader left, grade right (screen-reader name is on the art) */}
      <span className={styles.label} aria-hidden="true">
        <span className={styles.grader}>{grading}</span>
        {grade && (
          <span className={styles.gradeWrap}>
            <span className={styles.gradeCap}>Grade</span>
            <span className={styles.grade}>{grade}</span>
          </span>
        )}
      </span>
      <span className={styles.art}>
        {/* The accessible name carries the slab context so the label can stay aria-hidden */}
        <CardImage src={src} alt={`${label} slab, ${alt}`} size={size} eager={eager} />
      </span>
    </span>
  )
}
