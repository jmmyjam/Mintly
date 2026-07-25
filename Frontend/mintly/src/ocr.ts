// Client-side OCR for the card scanner. Everything here runs in the browser via
// Tesseract.js (WASM) — the captured image never leaves the device; only the
// text we read from it is later handed to the normal card-lookup endpoints.
//
// The card NAME is the primary signal: it's large, high-contrast, and the
// easiest text to read. The collector NUMBER (bottom of the card, e.g.
// "025/165") is a refiner that's often too small/stylised to read cleanly — so
// callers must still work when only the name comes back (see Scan.tsx's
// name-first lookup).
//
// Tesseract's worker/core/language assets are fetched from its default CDN on
// first use and then cached by the browser. To make the feature fully offline,
// copy tesseract.js/dist/worker.min.js, the tesseract.js-core files, and
// eng.traineddata.gz into public/tesseract/ and set workerPath/corePath/langPath
// on WORKER_OPTIONS below — nothing else changes.

import { createWorker, PSM, type Worker } from 'tesseract.js'

// Flip these to self-hosted paths (e.g. '/tesseract/worker.min.js') to drop the
// CDN dependency; left empty, Tesseract uses its bundled CDN defaults.
const WORKER_OPTIONS: { workerPath?: string; corePath?: string; langPath?: string } = {}

export interface CardReading {
  name: string
  number: string // normalised toward the catalog's stored form (e.g. "25")
  rawNumber: string // what OCR actually saw, for the editable field / display
  // Populated only when readCard is called with { debug: true } — lets the /scan
  // page surface exactly what OCR was given and what it returned.
  debug?: {
    nameCropUrl: string
    numberCropUrl: string
    rawName: string // unparsed OCR text of the name crop
    rawNumber: string // unparsed OCR text of the number crop
  }
}

// Reused across scans on one worker, so both passes must set a non-empty
// whitelist every call — an empty string does NOT reliably clear a previously
// set whitelist in Tesseract, which would otherwise strip lowercase letters
// from the name after the first (uppercase-only) number pass.
const NAME_WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz '.&-"
const NUMBER_WHITELIST = '0123456789/ABCDEFGHIJKLMNOPQRSTUVWXYZ'

let workerPromise: Promise<Worker> | null = null

// One worker for the page session; creating it downloads the language model, so
// it's lazy and reused across scans.
function getWorker(): Promise<Worker> {
  if (!workerPromise) {
    workerPromise = createWorker('eng', undefined, WORKER_OPTIONS).catch((err) => {
      // Surface a worker/asset load failure instead of it vanishing into the
      // caller's generic "couldn't read" message; allow a later retry.
      console.error('[scan] Tesseract worker failed to load', err)
      workerPromise = null
      throw err
    })
  }
  return workerPromise
}

// Optional: kick off the (slow) first-load download ahead of the first capture.
export function warmUpOcr(): void {
  void getWorker()
}

// Grayscale + a firm contrast stretch (helps Tesseract's internal binarisation
// separate text from a busy/holo background). No hard threshold — that would
// misfire on white-on-dark full-art names.
function grayscaleContrast(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const img = ctx.getImageData(0, 0, w, h)
  const d = img.data
  for (let i = 0; i < d.length; i += 4) {
    const g = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]
    const v = Math.max(0, Math.min(255, (g - 128) * 1.45 + 128))
    d[i] = d[i + 1] = d[i + 2] = v
  }
  ctx.putImageData(img, 0, 0)
}

// A light sharpen (cross kernel) to claw back edge detail lost to camera blur —
// blur was the main thing crippling the read. Operates on the grey channel.
function sharpen(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const src = ctx.getImageData(0, 0, w, h).data
  const out = ctx.createImageData(w, h)
  const d = out.data
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const idx = (y * w + x) * 4
      const up = (Math.max(0, y - 1) * w + x) * 4
      const down = (Math.min(h - 1, y + 1) * w + x) * 4
      const left = (y * w + Math.max(0, x - 1)) * 4
      const right = (y * w + Math.min(w - 1, x + 1)) * 4
      const v = Math.max(0, Math.min(255, 5 * src[idx] - src[up] - src[down] - src[left] - src[right]))
      d[idx] = d[idx + 1] = d[idx + 2] = v
      d[idx + 3] = 255
    }
  }
  ctx.putImageData(out, 0, 0)
}

// Crop a sub-region of the source (fractions 0..1) and prepare it for OCR:
// upscale so the crop is at least `minOutHeight` tall (small card text OCRs far
// better at higher resolution), then grayscale + contrast + sharpen.
function cropRegion(
  src: HTMLCanvasElement,
  fx: number,
  fy: number,
  fw: number,
  fh: number,
  minOutHeight = 360,
): HTMLCanvasElement {
  const sx = Math.round(src.width * fx)
  const sy = Math.round(src.height * fy)
  const sw = Math.max(1, Math.round(src.width * fw))
  const sh = Math.max(1, Math.round(src.height * fh))

  const scale = Math.min(4, Math.max(1.5, minOutHeight / sh))
  const out = document.createElement('canvas')
  out.width = Math.round(sw * scale)
  out.height = Math.round(sh * scale)
  const ctx = out.getContext('2d')!
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(src, sx, sy, sw, sh, 0, 0, out.width, out.height)

  grayscaleContrast(ctx, out.width, out.height)
  sharpen(ctx, out.width, out.height)
  return out
}

// Pull the collector number out of a noisy OCR string.
// Handles the printed "025/165" form (take the numerator) and lettered promo
// codes like "SWSH039", "SV042", "TG12", "GG05", "H12".
function parseNumber(text: string): string {
  const up = text.toUpperCase()

  const slash = up.match(/(\d{1,3})\s*[/\\|]\s*(\d{1,3})/)
  if (slash) return slash[1]

  const promo = up.match(/\b([A-Z]{1,4})[-\s]?(\d{1,4})\b/)
  if (promo) return `${promo[1]}${promo[2]}`

  const bare = up.match(/\b(\d{1,4})\b/)
  if (bare) return bare[1]

  return ''
}

// Normalise a scanned number toward how pokemontcg.io stores it in the catalog,
// which `/cards?number=` matches EXACTLY. Numeric numbers are stored un-padded
// ("025" -> "25"); lettered promo codes keep their form. A perfect match isn't
// required — the scan flow falls back to a name-only lookup — this just makes
// the precise (name + number) query land more often.
// Mirrors the intent of tcgcsv.norm_number (Backend/app/services/tcgcsv.py).
export function normNumber(raw: string): string {
  const head = raw.split(/[/\\|]/)[0].trim()
  if (!head) return ''
  if (/^\d+$/.test(head)) return String(parseInt(head, 10))
  return head.toUpperCase()
}

// Clean the OCR'd name band into something searchable. OCR reads the space in a
// name as an apostrophe and stylized logos ("ex") as punctuation like "&", so we
// drop everything except letters, spaces, and hyphens (kept for "Ho-Oh"), then
// pick the most letter-dense line (the name, over the Stage badge / evolution
// text). The catalog does a substring match, so "mega feraligatr" still finds
// "Mega Feraligatr ex".
function parseName(text: string): string {
  const lines = text
    .split('\n')
    .map((line) =>
      line
        .replace(/[^A-Za-z\s-]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim(),
    )
    .filter((line) => line.replace(/[^A-Za-z]/g, '').length >= 3)

  if (lines.length === 0) return ''
  lines.sort((a, b) => b.replace(/[^A-Za-z]/g, '').length - a.replace(/[^A-Za-z]/g, '').length)
  return lines[0]
}

// Read a captured card image (already cropped to the card frame by the
// viewfinder). Returns best-effort name + number; either may be empty. Pass
// { debug: true } to also get the crops and raw OCR text back for inspection.
export async function readCard(
  card: HTMLCanvasElement,
  opts: { debug?: boolean } = {},
): Promise<CardReading> {
  try {
    const worker = await getWorker()

    // Name band: top of the card, left ~74% so the HP/energy symbols on the right
    // don't bleed into the read. Kept generous vertically so a slightly
    // misaligned card still catches the name line. SINGLE_BLOCK (not SINGLE_LINE)
    // so Tesseract segments the band into lines — the crop also contains the
    // Stage badge and the evolution box — and parseName picks the name line out.
    const nameImg = cropRegion(card, 0.03, 0.02, 0.71, 0.2)
    await worker.setParameters({
      tessedit_pageseg_mode: PSM.SINGLE_BLOCK,
      tessedit_char_whitelist: NAME_WHITELIST,
    })
    const rawNameText = (await worker.recognize(nameImg)).data.text
    const name = parseName(rawNameText)

    // Number: the very bottom-left strip — the collector number (e.g. "043/217")
    // sits right at the card's bottom edge. Kept shallow so attack text above it
    // doesn't drown it out. SINGLE_BLOCK because the corner often stacks the
    // number over a set code / artist line.
    const numImg = cropRegion(card, 0.02, 0.9, 0.5, 0.085)
    await worker.setParameters({
      tessedit_pageseg_mode: PSM.SINGLE_BLOCK,
      tessedit_char_whitelist: NUMBER_WHITELIST,
    })
    const rawNumberText = (await worker.recognize(numImg)).data.text
    const rawNumber = parseNumber(rawNumberText)

    const reading: CardReading = { name, number: normNumber(rawNumber), rawNumber }
    if (opts.debug) {
      reading.debug = {
        nameCropUrl: nameImg.toDataURL('image/png'),
        numberCropUrl: numImg.toDataURL('image/png'),
        rawName: rawNameText.trim(),
        rawNumber: rawNumberText.trim(),
      }
    }
    return reading
  } catch (err) {
    console.error('[scan] OCR failed', err)
    throw err
  }
}
