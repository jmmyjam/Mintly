import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PriceQtyForm from './PriceQtyForm'
import { axe } from '../test/utils'

// A no-op set of the required callbacks, overridable per test.
function noop() {}

describe('PriceQtyForm', () => {
  it('associates labels with the inputs in labeled mode', () => {
    render(
      <PriceQtyForm
        price="10"
        quantity="1"
        onPriceChange={noop}
        onQuantityChange={noop}
        onSubmit={noop}
        submitLabel="Add"
        labeled
      />,
    )
    expect(screen.getByLabelText('Price paid ($)')).toHaveValue(10)
    expect(screen.getByLabelText('Quantity')).toHaveValue(1)
  })

  it('marks the price required and explains why when adding a graded lot', () => {
    render(
      <PriceQtyForm
        price=""
        quantity="1"
        onPriceChange={noop}
        onQuantityChange={noop}
        onSubmit={noop}
        submitLabel="Add"
        labeled
        priceRequired
      />,
    )
    const price = screen.getByLabelText(/Price paid \(\$\)/)
    expect(price).toHaveAttribute('aria-required', 'true')
    // The reason is on the page, not just an asterisk
    const hint = screen.getByText(/cannot fill this in from the market price/)
    expect(hint).toBeInTheDocument()
    expect(price).toHaveAttribute('aria-describedby', hint.id)
    // A mis-keyed CSS-module class is silently undefined and renders unstyled,
    // with nothing in the build or the type-check to catch it
    expect(hint.className).toBeTruthy()
    expect(screen.getByText('*').className).toBeTruthy()
  })

  it('carries "required" in the accessible name when the field has no visible label', () => {
    // Compact mode has only a placeholder, and the asterisk used in labeled mode
    // is decorative — so the requirement has to live in the accessible name
    render(
      <PriceQtyForm
        price=""
        quantity="1"
        onPriceChange={noop}
        onQuantityChange={noop}
        onSubmit={noop}
        submitLabel="Add"
        priceRequired
      />,
    )
    expect(screen.getByLabelText('Price paid ($), required')).toBeInTheDocument()
  })

  it('leaves the price field unmarked for a raw lot', () => {
    render(
      <PriceQtyForm
        price=""
        quantity="1"
        onPriceChange={noop}
        onQuantityChange={noop}
        onSubmit={noop}
        submitLabel="Add"
        labeled
      />,
    )
    expect(screen.getByLabelText('Price paid ($)')).not.toHaveAttribute('aria-required')
    expect(screen.queryByText(/market price/)).not.toBeInTheDocument()
  })

  it('has no accessibility violations in the graded required state', async () => {
    const { container } = render(
      <PriceQtyForm
        price=""
        quantity="1"
        onPriceChange={noop}
        onQuantityChange={noop}
        onSubmit={noop}
        submitLabel="Add"
        labeled
        priceRequired
      />,
    )
    expect(await axe(container)).toHaveNoViolations()
  })

  it('reports edits through onPriceChange / onQuantityChange', async () => {
    const onPriceChange = vi.fn()
    const onQuantityChange = vi.fn()
    const user = userEvent.setup()
    render(
      <PriceQtyForm
        price=""
        quantity=""
        onPriceChange={onPriceChange}
        onQuantityChange={onQuantityChange}
        onSubmit={noop}
        submitLabel="Add"
        labeled
      />,
    )
    await user.type(screen.getByLabelText('Price paid ($)'), '5')
    expect(onPriceChange).toHaveBeenCalledWith('5')
    await user.type(screen.getByLabelText('Quantity'), '2')
    expect(onQuantityChange).toHaveBeenCalledWith('2')
  })

  it('submits the form when the primary button is clicked', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(
      <PriceQtyForm
        price="10"
        quantity="1"
        onPriceChange={noop}
        onQuantityChange={noop}
        onSubmit={onSubmit}
        submitLabel="Add to portfolio"
        labeled
      />,
    )
    await user.click(screen.getByRole('button', { name: 'Add to portfolio' }))
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('shows the busy label and disables submit while busy', () => {
    render(
      <PriceQtyForm
        price="10"
        quantity="1"
        onPriceChange={noop}
        onQuantityChange={noop}
        onSubmit={noop}
        submitLabel="Add"
        busyLabel="Adding…"
        busy
        labeled
      />,
    )
    expect(screen.getByRole('button', { name: 'Adding…' })).toBeDisabled()
  })

  it('renders a Cancel button that calls onCancel', async () => {
    const onCancel = vi.fn()
    const user = userEvent.setup()
    render(
      <PriceQtyForm
        price="10"
        quantity="1"
        onPriceChange={noop}
        onQuantityChange={noop}
        onSubmit={noop}
        onCancel={onCancel}
        submitLabel="Save"
        labeled
      />,
    )
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('names the inputs with an aria-label in compact mode (placeholders are not names)', () => {
    render(
      <PriceQtyForm
        price=""
        quantity=""
        onPriceChange={noop}
        onQuantityChange={noop}
        onSubmit={noop}
        submitLabel="Add"
      />,
    )
    expect(screen.getByLabelText('Price paid ($)')).toBeInTheDocument()
    expect(screen.getByLabelText('Quantity')).toBeInTheDocument()
  })

  it('has no accessibility violations in labeled mode', async () => {
    const { container } = render(
      <PriceQtyForm
        price=""
        quantity=""
        onPriceChange={noop}
        onQuantityChange={noop}
        onSubmit={noop}
        submitLabel="Add"
        labeled
      />,
    )
    expect(await axe(container)).toHaveNoViolations()
  })

  it('has no accessibility violations in compact mode', async () => {
    const { container } = render(
      <PriceQtyForm
        price=""
        quantity=""
        onPriceChange={noop}
        onQuantityChange={noop}
        onSubmit={noop}
        submitLabel="Add"
      />,
    )
    expect(await axe(container)).toHaveNoViolations()
  })
})
