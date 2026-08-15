// Shared condition/grade vocabulary + helpers (roadmap #7), pure and unit-tested
// like `format`/`variants`. Keep GRADING_TYPES / RAW_CONDITIONS in sync with the
// backend's GRADING_TYPES + _clean_condition in app/routers/portfolio.py.

export const GRADING_TYPES = ['Raw', 'PSA', 'BGS', 'CGC', 'SGC', 'Other'] as const
export type Grading = (typeof GRADING_TYPES)[number]

// TCGplayer's raw condition ladder — the `grade` value when grading is "Raw".
export const RAW_CONDITIONS = [
  'Near Mint', 'Lightly Played', 'Moderately Played', 'Heavily Played', 'Damaged',
]

// Grade options offered per grader (free text for "Other"). grade is capped at 24
// chars server-side, so these all fit.
export const GRADE_OPTIONS: Record<string, string[]> = {
  PSA: ['10', '9', '8', '7', '6', '5', '4', '3', '2', '1', 'Authentic'],
  BGS: ['10 (Black Label)', '10', '9.5', '9', '8.5', '8', '7.5', '7', '6.5', '6'],
  CGC: ['10 (Pristine)', '10', '9.5', '9', '8.5', '8', '7.5', '7', '6.5', '6'],
  SGC: ['10 (Pristine)', '10', '9.5', '9', '8.5', '8', '7', '6', '5'],
}

// The add picker's starting point: a raw near-mint card — consistent with the raw
// TCGplayer market price the add form auto-fills.
export const DEFAULT_GRADING = 'Raw'
export const DEFAULT_GRADE = 'Near Mint'

// A graded slab — valued at cost until phase-2 graded prices (mirrors the
// backend's _is_graded: anything with a grading that isn't Raw/unset).
export function isGraded(grading: string | null | undefined): boolean {
  return grading != null && grading !== 'Raw'
}

// The value options for a grading type (RAW_CONDITIONS for Raw, the grader's list
// otherwise). Empty for "Other" (free text).
export function gradeOptions(grading: string): string[] {
  if (grading === 'Raw') return RAW_CONDITIONS
  return GRADE_OPTIONS[grading] ?? []
}

// A short label for a lot's condition: "PSA 10", "Near Mint", or "" when unset.
export function conditionLabel(grading: string | null | undefined, grade: string | null | undefined): string {
  if (!grading) return ''
  if (grading === 'Raw') return grade || 'Raw'
  return grade ? `${grading} ${grade}` : grading
}

// The Option B holding key: lots sharing (card_id, grading, grade) are one holding
// (the Portfolio grid tiles them separately). Null grading/grade collapse to '' so
// pre-feature/unset lots group together.
export function holdingKey(cardId: string, grading: string | null | undefined, grade: string | null | undefined): string {
  return `${cardId}|${grading ?? ''}|${grade ?? ''}`
}

// The condition half of a holding, used as the Holding route's `?g=` param and to
// match a lot to it. '' = unset/raw-unspecified (also what a legacy bare
// /portfolio/:cardId link resolves to).
export function conditionKey(grading: string | null | undefined, grade: string | null | undefined): string {
  if (!grading) return ''
  return `${grading}|${grade ?? ''}`
}
