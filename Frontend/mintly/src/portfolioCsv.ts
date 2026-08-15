import type { PortfolioCard, BatchAddItem } from './api'
import { GRADING_TYPES } from './grading'

// Portfolio CSV round-trip. Export writes one row per lot (one portfolio_cards
// row) so a Mintly-exported file re-imports through the batch adder exactly.
// Numbers are written raw (no $ or thousands separators) so spreadsheets treat
// them as numbers and re-import parses them cleanly. Import is tolerant: it maps
// columns by header name, needs only card_id, and fills sensible defaults.

const COLUMNS = [
  'card_id',
  'name',
  'quantity',
  'purchase_price',
  'purchase_date',
  'grading',
  'grade',
  'current_price',
  'market_value',
  'cost_basis',
  'gain_loss',
  'gain_loss_pct',
] as const

// RFC-4180: quote a field containing a comma, quote, CR, or LF; double any quote.
function escapeField(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

// Guard spreadsheet formula injection: a text cell starting with = + - @ (or a
// leading tab/CR) can execute in Excel/Sheets. Only the free-text name column can
// carry this (numeric columns must stay numbers), so neutralize it with a leading
// apostrophe. Pokemon names never trip it, but user data shouldn't be trusted.
function safeText(value: string): string {
  return /^[=+\-@\t\r]/.test(value) ? `'${value}` : value
}

function num(value: number | null | undefined): string {
  return value == null ? '' : String(value)
}

// Serialize the portfolio (one row per lot) to a CSV string.
export function toPortfolioCsv(cards: PortfolioCard[]): string {
  const rows = [COLUMNS.join(',')]
  for (const c of cards) {
    const marketValue = c.current_price != null ? c.current_price * c.quantity : null
    const fields = [
      c.card_id,
      safeText(c.card_name),
      String(c.quantity),
      num(c.purchase_price),
      c.purchase_date ?? '',
      safeText(c.grading ?? ''),
      safeText(c.grade ?? ''),
      num(c.current_price),
      num(marketValue),
      num(c.purchase_price * c.quantity),
      num(c.gain_loss),
      num(c.gain_loss_pct),
    ]
    rows.push(fields.map(escapeField).join(','))
  }
  return rows.join('\r\n')
}

// Minimal RFC-4180 reader: handles quoted fields (embedded commas, quotes, and
// newlines) and \n / \r\n / bare-\r line endings.
function parseCsv(text: string): string[][] {
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1) // strip a UTF-8 BOM
  const records: string[][] = []
  let field = ''
  let record: string[] = []
  let inQuotes = false
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i++ } // escaped quote
        else inQuotes = false
      } else field += ch
      continue
    }
    if (ch === '"') inQuotes = true
    else if (ch === ',') { record.push(field); field = '' }
    else if (ch === '\n') { record.push(field); records.push(record); record = []; field = '' }
    else if (ch === '\r') {
      if (text[i + 1] === '\n') continue // let the \n finish the record
      record.push(field); records.push(record); record = []; field = ''
    } else field += ch
  }
  if (field !== '' || record.length > 0) { record.push(field); records.push(record) }
  return records
}

export interface ParsedPortfolioCsv {
  items: BatchAddItem[]
  skipped: number // rows dropped for a missing card_id
  total: number   // data rows seen (excludes header + blank lines)
}

// Parse a CSV into batch-add items. Columns map by header name (case-insensitive,
// extra/re-ordered columns tolerated); a file with no recognizable header falls
// back to positional card_id, purchase_price, quantity, purchase_date — the
// minimal hand-made shape. card_id is required (rows without it are skipped and
// counted); a blank/invalid price becomes null (backend uses market price); a
// blank/invalid quantity becomes 1; a blank date is omitted (backend stamps now).
export function parsePortfolioCsv(text: string): ParsedPortfolioCsv {
  const records = parseCsv(text).filter(r => r.some(f => f.trim() !== ''))
  if (records.length === 0) return { items: [], skipped: 0, total: 0 }

  const header = records[0].map(h => h.trim().toLowerCase())
  const known = ['card_id', 'purchase_price', 'quantity', 'purchase_date']
  const hasHeader = known.some(k => header.includes(k))
  const dataRows = hasHeader ? records.slice(1) : records
  const col = hasHeader
    ? { id: header.indexOf('card_id'), price: header.indexOf('purchase_price'), qty: header.indexOf('quantity'), date: header.indexOf('purchase_date'), grading: header.indexOf('grading'), grade: header.indexOf('grade') }
    : { id: 0, price: 1, qty: 2, date: 3, grading: -1, grade: -1 }

  const cell = (row: string[], i: number) => (i >= 0 ? row[i] ?? '' : '').trim()

  const items: BatchAddItem[] = []
  let skipped = 0
  for (const row of dataRows) {
    const cardId = cell(row, col.id)
    if (!cardId) { skipped++; continue }

    const rawPrice = cell(row, col.price).replace(/[$,]/g, '')
    const price = rawPrice === '' ? NaN : Number(rawPrice)
    const purchase_price = Number.isFinite(price) && price >= 0 ? price : null

    const qty = Math.floor(Number(cell(row, col.qty).replace(/,/g, '')))
    const quantity = Number.isFinite(qty) && qty >= 1 ? qty : 1

    const rawDate = cell(row, col.date)
    const purchase_date = rawDate === '' ? null : rawDate

    // Condition/grade (roadmap #7). Only a known grading is kept — an unknown
    // value would 422 the whole batch server-side; a graded case with no grade
    // is dropped to unset (a slab must carry its grade). Old files without these
    // columns import as unset.
    const rawGrading = cell(row, col.grading)
    let grading = (GRADING_TYPES as readonly string[]).includes(rawGrading) ? rawGrading : null
    let grade = grading ? (cell(row, col.grade) || null) : null
    if (grading && grading !== 'Raw' && !grade) { grading = null; grade = null }

    items.push({ card_id: cardId, purchase_price, quantity, purchase_date, grading, grade })
  }
  return { items, skipped, total: dataRows.length }
}
