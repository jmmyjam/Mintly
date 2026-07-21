import type { PricePoint } from './api'

// Shared vocabulary for TCGPlayer price variants: display labels, the fixed
// chart color per variant, and the preference order that picks the "primary"
// variant (must match extract_price in Backend/app/services/price_history.py).

export const PRICE_PREFERENCE = ['holofoil', 'normal', 'reverseHolofoil', '1stEditionHolofoil']

const VARIANT_LABELS: { [key: string]: string } = {
  normal: 'Normal',
  holofoil: 'Holofoil',
  reverseHolofoil: 'Reverse Holofoil',
  '1stEditionHolofoil': '1st Edition Holofoil',
  '1stEditionNormal': '1st Edition Normal',
  unlimitedHolofoil: 'Unlimited Holofoil',
}

// Compact labels for the chart's line-end tags, where the full names collide
const VARIANT_SHORT: { [key: string]: string } = {
  normal: 'Normal',
  holofoil: 'Holo',
  reverseHolofoil: 'Reverse',
  '1stEditionHolofoil': '1st Ed Holo',
  '1stEditionNormal': '1st Ed',
  unlimitedHolofoil: 'Unlimited',
}

// Fixed color per variant NAME (never assigned by position, so a variant keeps
// its color on every card and when others are absent). Validated for the dark
// surface + colorblind separation; the chart's line-end labels are the
// secondary encoding that backs the closest pair up.
const VARIANT_COLORS: { [key: string]: string } = {
  holofoil: '#3987e5',
  normal: '#008300',
  reverseHolofoil: '#d55181',
  '1stEditionHolofoil': '#c98500',
  '1stEditionNormal': '#9085e9',
  unlimitedHolofoil: '#d95926',
}

const FALLBACK_COLOR = '#9c9ca4' // unknown variant keys render neutral

export function variantLabel(key: string) {
  return VARIANT_LABELS[key] || key
}

export function variantShortLabel(key: string) {
  return VARIANT_SHORT[key] || key
}

export function variantColor(key: string) {
  return VARIANT_COLORS[key] || FALLBACK_COLOR
}

// Display order: preference order first, unknown keys after, alphabetical
export function sortVariants(keys: string[]): string[] {
  const rank = (k: string) => {
    const i = PRICE_PREFERENCE.indexOf(k)
    return i === -1 ? PRICE_PREFERENCE.length : i
  }
  return [...keys].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
}

// The headline history series predates per-variant tracking, and by
// construction it IS the preferred variant's price — so backfill the preferred
// variant's series with headline points from before its own coverage starts.
// The chart and the variant table both read this merged view.
export function mergeHeadline(
  points: PricePoint[],
  variants: { [key: string]: PricePoint[] },
): { [key: string]: PricePoint[] } {
  const keys = sortVariants(Object.keys(variants))
  if (keys.length === 0 || points.length === 0) return variants
  const preferred = keys[0]
  const series = variants[preferred]
  const firstTracked = series.length > 0 ? series[0].date : undefined
  const backfill = points.filter(p => firstTracked === undefined || p.date < firstTracked)
  if (backfill.length === 0) return variants
  return { ...variants, [preferred]: [...backfill, ...series] }
}
