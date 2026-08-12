import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { UserEvent } from '@testing-library/user-event'
import Scan from './Scan'
import { scanCard, addCardBatch, addCard, reportScanFeedback, getToken, type Card } from '../api'
import { axe, renderWithRouter } from '../test/utils'

// api: keep the pure helpers + the SessionExpiredError class real (getCardPrice,
// errorMessage, getCardImageUrl are used by Scan and its children), stub only the
// network fns and the token read.
vi.mock('../api', async (importActual) => {
  const actual = await importActual<typeof import('../api')>()
  return {
    ...actual,
    scanCard: vi.fn(),
    addCardBatch: vi.fn(),
    addCard: vi.fn(),
    reportScanFeedback: vi.fn(),
    getToken: vi.fn(() => 'test-token'),
  }
})

// portfolios: a stable single-portfolio store (PortfolioPicker + Scan read it).
vi.mock('../portfolios', () => {
  const portfolio = {
    id: 1,
    name: 'My Portfolio',
    is_default: true,
    created_at: '',
    card_count: 0,
  }
  return {
    usePortfolios: () => ({
      portfolios: [portfolio],
      active: portfolio,
      activeId: 1,
      setActive: vi.fn(),
      refresh: vi.fn(),
      loaded: true,
    }),
    clearPortfolios: vi.fn(),
  }
})

// --- jsdom capture plumbing -------------------------------------------------
// The camera is unsupported under jsdom (no navigator.mediaDevices), so
// CameraViewfinder falls into its "Choose a photo" file fallback. That path runs
// `new Image()` → imageToCanvas() (canvas 2d context) → onCapture(canvas), and
// Scan's handleCapture then calls canvas.toDataURL()/toBlob(). jsdom implements
// none of those, so stub the minimum with plain functions (plain, not vi.fn, so
// the suite's restoreMocks can't wipe them mid-run) to make the real file → scan
// path drivable end to end.
class FakeImage {
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  width = 245
  height = 342
  naturalWidth = 245
  naturalHeight = 342
  private _src = ''
  get src() {
    return this._src
  }
  set src(value: string) {
    this._src = value
    // onload is assigned before .src in CameraViewfinder.onFile, so firing
    // synchronously here drives the capture within the upload's act() scope.
    this.onload?.()
  }
}

beforeAll(() => {
  const proto = HTMLCanvasElement.prototype as unknown as Record<string, unknown>
  proto.getContext = () => ({ drawImage() {} })
  proto.toDataURL = () => 'data:image/jpeg;base64,AAAA'
  proto.toBlob = (cb: BlobCallback) => cb(new Blob(['x'], { type: 'image/jpeg' }))
  URL.createObjectURL = () => 'blob:test'
  URL.revokeObjectURL = () => {}
  ;(globalThis as unknown as { Image: unknown }).Image = FakeImage
})

// --- fixtures ---------------------------------------------------------------
function makeCard(overrides: Partial<Card> = {}): Card {
  return {
    id: 'sv1-1',
    name: 'Charizard ex',
    number: '1',
    images: { small: 'https://img.test/small.png', large: 'https://img.test/large.png' },
    set: { name: 'Scarlet & Violet', id: 'sv1' },
    ...overrides,
  }
}

// Drive a capture through the real "Choose a photo" file fallback.
async function captureViaFile(user: UserEvent) {
  const input = await screen.findByLabelText(/choose a photo/i)
  await user.upload(input, new File(['img'], 'card.png', { type: 'image/png' }))
}

describe('Scan page', () => {
  describe('logged out', () => {
    beforeEach(() => {
      vi.mocked(getToken).mockReturnValue(null)
    })

    it('shows the scan SignedOutHero promo instead of the scanner, and never scans', () => {
      const { container } = renderWithRouter(<Scan />)

      // Hero pitch, not the scanner: no Single/Batch toggle, no capture UI.
      expect(screen.getByText('Camera scanner')).toBeInTheDocument()
      expect(
        screen.getByRole('heading', { level: 1, name: /scan any card/i }),
      ).toBeInTheDocument()
      // The three how-it-works steps.
      expect(screen.getByText('Frame the card.')).toBeInTheDocument()
      expect(screen.getByText('Confirm the match.')).toBeInTheDocument()
      expect(screen.getByText('Queue the stack.')).toBeInTheDocument()
      // CTA row: a Log in pill + a register-tab link.
      expect(screen.getByRole('link', { name: 'Log in' })).toHaveAttribute('href', '/login')
      expect(screen.getByRole('link', { name: 'Create a free account' })).toBeInTheDocument()

      expect(screen.queryByRole('group', { name: 'Scan mode' })).not.toBeInTheDocument()
      expect(scanCard).not.toHaveBeenCalled()
      // sanity: container rendered the hero
      expect(container.querySelector('h1')).not.toBeNull()
    })

    it('the signed-out hero has no accessibility violations', async () => {
      const { container } = renderWithRouter(<Scan />)
      expect(await axe(container)).toHaveNoViolations()
    })
  })

  describe('signed in', () => {
    beforeEach(() => {
      vi.mocked(getToken).mockReturnValue('test-token')
    })

    it('renders the scanner with a Single/Batch toggle, Single selected by default', async () => {
      renderWithRouter(<Scan />)

      expect(screen.getByRole('heading', { level: 1, name: 'Scan a card' })).toBeInTheDocument()
      const toggle = screen.getByRole('group', { name: 'Scan mode' })
      expect(toggle).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Single' })).toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByRole('button', { name: 'Batch add' })).toHaveAttribute(
        'aria-pressed',
        'false',
      )
      // Camera is unsupported in jsdom → the file fallback is what renders.
      expect(await screen.findByLabelText(/choose a photo/i)).toBeInTheDocument()
    })

    it('the signed-in default state has no accessibility violations', async () => {
      const { container } = renderWithRouter(<Scan />)
      await screen.findByLabelText(/choose a photo/i)
      expect(await axe(container)).toHaveNoViolations()
    })

    it('switching to Batch shows the queue with its empty state and a disabled Add all', async () => {
      const user = userEvent.setup()
      renderWithRouter(<Scan />)

      await user.click(screen.getByRole('button', { name: 'Batch add' }))

      expect(screen.getByRole('button', { name: 'Batch add' })).toHaveAttribute(
        'aria-pressed',
        'true',
      )
      // Batch-only affordances.
      expect(screen.getByText(/Scanned cards collect here/i)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Add all to portfolio' })).toBeDisabled()
      // The batch queue's portfolio picker (allowCreate).
      expect(screen.getByLabelText('Add batch to portfolio')).toBeInTheDocument()
    })

    it('single-mode capture renders the best guess, its confidence badge, and Other matches', async () => {
      const user = userEvent.setup()
      vi.mocked(scanCard).mockResolvedValue({
        data: [
          makeCard({
            id: 'sv1-1',
            name: 'Charizard ex',
            matchScore: 0.93,
            tcgplayer: { prices: { holofoil: { market: 350 } } },
          }),
          makeCard({ id: 'sv1-2', name: 'Pikachu', number: '2', matchScore: 0.78 }),
          makeCard({ id: 'sv1-3', name: 'Bulbasaur', number: '3', matchScore: 0.55 }),
        ],
        page: 1,
        pageSize: 50,
        totalCount: 3,
      })
      renderWithRouter(<Scan />)

      await captureViaFile(user)

      // Best guess block.
      expect(await screen.findByRole('heading', { name: 'We think this is…' })).toBeInTheDocument()
      expect(screen.getByText('93% match')).toBeInTheDocument()
      expect(screen.getByText('Charizard ex')).toBeInTheDocument()
      // Seeded add row pre-fills the best guess's market price.
      expect(screen.getByLabelText('Price paid')).toHaveValue(350)

      // Other matches grid, with each candidate's rounded confidence.
      expect(screen.getByRole('heading', { name: 'Other matches' })).toBeInTheDocument()
      expect(screen.getByText('Pikachu')).toBeInTheDocument()
      expect(screen.getByText('Bulbasaur')).toBeInTheDocument()
      expect(screen.getByText('78%')).toBeInTheDocument()
      expect(screen.getByText('55%')).toBeInTheDocument()
    })

    it('single-mode best-guess Add posts addCard with the seeded price/qty', async () => {
      const user = userEvent.setup()
      vi.mocked(scanCard).mockResolvedValue({
        data: [
          makeCard({
            id: 'sv1-1',
            name: 'Charizard ex',
            matchScore: 0.9,
            tcgplayer: { prices: { holofoil: { market: 350 } } },
          }),
        ],
        page: 1,
        pageSize: 50,
        totalCount: 1,
      })
      vi.mocked(addCard).mockResolvedValue('Added to portfolio!')
      renderWithRouter(<Scan />)

      await captureViaFile(user)
      await screen.findByRole('heading', { name: 'We think this is…' })

      await user.click(screen.getByRole('button', { name: 'Add to portfolio' }))

      await waitFor(() =>
        expect(addCard).toHaveBeenCalledWith('sv1-1', 350, 1, 1),
      )
      expect(await screen.findByText('Added to portfolio!')).toBeInTheDocument()

      // Confirming the best guess logs an anonymous accuracy label at rank 0.
      await waitFor(() =>
        expect(reportScanFeedback).toHaveBeenCalledWith([
          expect.objectContaining({
            outcome: 'confirmed',
            picked_rank: 0,
            picked_card_id: 'sv1-1',
            top_card_id: 'sv1-1',
            picked_score: 0.9,
            top_score: 0.9,
          }),
        ]),
      )
    })

    it('batch capture prepends the scan to the queue and Add all posts one addCardBatch', async () => {
      const user = userEvent.setup()
      vi.mocked(scanCard).mockResolvedValue({
        data: [
          makeCard({
            id: 'sv1-1',
            name: 'Charizard ex',
            matchScore: 0.93,
            tcgplayer: { prices: { holofoil: { market: 12.5 } } },
          }),
        ],
        page: 1,
        pageSize: 50,
        totalCount: 1,
      })
      vi.mocked(addCardBatch).mockResolvedValue({
        added: 1,
        failed: [],
        message: 'Added 1 card to portfolio',
      })
      renderWithRouter(<Scan />)

      await user.click(screen.getByRole('button', { name: 'Batch add' }))
      await captureViaFile(user)

      // Row landed: matched card, confidence badge, seeded price, count pill.
      expect(await screen.findByText('93% match')).toBeInTheDocument()
      expect(screen.getByText('✓ Added Charizard ex to the batch')).toBeInTheDocument()
      expect(screen.getByLabelText('Price paid for Charizard ex')).toHaveValue(12.5)
      expect(screen.getByText(/1 card/)).toBeInTheDocument()

      await user.click(screen.getByRole('button', { name: 'Add all 1 to portfolio' }))

      await waitFor(() =>
        expect(addCardBatch).toHaveBeenCalledWith(
          [{ card_id: 'sv1-1', purchase_price: 12.5, quantity: 1 }],
          1,
        ),
      )
      // Each committed card logs one confirmed accuracy label (rank 0 here).
      await waitFor(() =>
        expect(reportScanFeedback).toHaveBeenCalledWith([
          expect.objectContaining({
            outcome: 'confirmed',
            picked_rank: 0,
            picked_card_id: 'sv1-1',
            top_score: 0.93,
          }),
        ]),
      )
      // Success clears the queue and shows the backend message.
      expect(await screen.findByText('Added 1 card to portfolio')).toBeInTheDocument()
      expect(screen.getByText(/Scanned cards collect here/i)).toBeInTheDocument()
    })

    it('flags a low-confidence batch scan with the amber "Check this" badge and banner', async () => {
      const user = userEvent.setup()
      vi.mocked(scanCard).mockResolvedValue({
        data: [
          makeCard({
            id: 'sv1-9',
            name: 'Blurry Card',
            matchScore: 0.5,
            tcgplayer: { prices: { holofoil: { market: 3 } } },
          }),
        ],
        page: 1,
        pageSize: 50,
        totalCount: 1,
      })
      renderWithRouter(<Scan />)

      await user.click(screen.getByRole('button', { name: 'Batch add' }))
      await captureViaFile(user)

      expect(await screen.findByText(/Check this · 50%/)).toBeInTheDocument()
      expect(screen.getByText(/1 card needs a look/i)).toBeInTheDocument()
    })

    it("a queued row's Change button opens the candidate picker modal", async () => {
      const user = userEvent.setup()
      vi.mocked(scanCard).mockResolvedValue({
        data: [
          makeCard({ id: 'sv1-1', name: 'Charizard ex', matchScore: 0.93 }),
          makeCard({ id: 'sv1-2', name: 'Charizard', number: '2', matchScore: 0.7 }),
        ],
        page: 1,
        pageSize: 50,
        totalCount: 2,
      })
      renderWithRouter(<Scan />)

      await user.click(screen.getByRole('button', { name: 'Batch add' }))
      await captureViaFile(user)
      await screen.findByText('93% match')

      await user.click(screen.getByRole('button', { name: 'Change' }))

      const dialog = screen.getByRole('dialog', { name: 'Choose the right card' })
      expect(dialog).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: 'Not the right card?' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Rescan this card' })).toBeInTheDocument()
    })
  })
})
