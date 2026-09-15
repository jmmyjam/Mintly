import { useId } from 'react'
import { GRADED_PRICE_HINT } from '../grading'
import styles from './PriceQtyForm.module.css'

// Shared price + quantity form: the Search add form (compact placeholders),
// the CardDetail add form (labeled fields), and the Portfolio lot editor.
interface PriceQtyFormProps {
  price: string
  quantity: string
  onPriceChange: (value: string) => void
  onQuantityChange: (value: string) => void
  onSubmit: () => void
  submitLabel: string
  busyLabel?: string
  busy?: boolean
  onCancel?: () => void
  labeled?: boolean
  smallButtons?: boolean
  className?: string
  // Adding a graded lot: the price is the only thing that can value it, so the
  // field says so up front instead of the add failing on submit. Marks the
  // input required, names it as required for screen readers, and (in labeled
  // mode, where there's room) explains why.
  priceRequired?: boolean
}

export default function PriceQtyForm({
  price,
  quantity,
  onPriceChange,
  onQuantityChange,
  onSubmit,
  submitLabel,
  busyLabel,
  busy = false,
  onCancel,
  labeled = false,
  smallButtons = false,
  className = 'add-form',
  priceRequired = false,
}: PriceQtyFormProps) {
  const sm = smallButtons ? ' btn-sm' : ''
  const hintId = useId()

  // In labeled mode the wrapping <label> names each input; in compact mode the
  // fields carry only a visual placeholder, so give them an aria-label too (a
  // placeholder is not an accessible name). When the price is required, that
  // accessible name has to carry it too — the asterisk beside the visible label
  // is decorative, and a compact field has no visible label at all.
  const priceInput = (
    <input
      type="number"
      placeholder={labeled ? undefined : priceRequired ? 'Price paid ($, required)' : 'Price paid($)'}
      aria-label={labeled ? undefined : priceRequired ? 'Price paid ($), required' : 'Price paid ($)'}
      value={price}
      onChange={e => onPriceChange(e.target.value)}
      className="mini-input"
      min="0"
      step="0.01"
      aria-required={priceRequired || undefined}
      aria-describedby={priceRequired && labeled ? hintId : undefined}
    />
  )
  const qtyInput = (
    <input
      type="number"
      placeholder={labeled ? undefined : 'Qty'}
      aria-label={labeled ? undefined : 'Quantity'}
      value={quantity}
      onChange={e => onQuantityChange(e.target.value)}
      className="mini-input mini-qty"
      min="1"
    />
  )
  const submitButton = (
    <button type="submit" className={`btn-primary${sm}`} disabled={busy}>
      {busy && busyLabel ? busyLabel : submitLabel}
    </button>
  )

  return (
    <form
      className={className}
      onSubmit={e => {
        e.preventDefault()
        onSubmit()
      }}
    >
      {labeled ? (
        <>
          <label className="edit-field">
            <span className="stat-label">
              Price paid ($)
              {priceRequired && <span className={styles.required}> *</span>}
            </span>
            {priceInput}
          </label>
          {priceRequired && (
            <p id={hintId} className={styles.hint}>{GRADED_PRICE_HINT}</p>
          )}
          <label className="edit-field">
            <span className="stat-label">Quantity</span>
            {qtyInput}
          </label>
        </>
      ) : (
        <>
          {priceInput}
          {qtyInput}
        </>
      )}
      {onCancel ? (
        <div className="add-form-buttons">
          {submitButton}
          <button type="button" className={`btn-outline${sm}`} disabled={busy} onClick={onCancel}>
            Cancel
          </button>
        </div>
      ) : (
        submitButton
      )}
    </form>
  )
}
