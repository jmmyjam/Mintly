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
