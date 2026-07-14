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
}: PriceQtyFormProps) {
  const sm = smallButtons ? ' btn-sm' : ''

  const priceInput = (
    <input
      type="number"
      placeholder={labeled ? undefined : 'Price paid($)'}
      value={price}
      onChange={e => onPriceChange(e.target.value)}
      className="mini-input"
      min="0"
      step="0.01"
    />
  )
  const qtyInput = (
    <input
      type="number"
      placeholder={labeled ? undefined : 'Qty'}
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
            <span className="stat-label">Price paid ($)</span>
            {priceInput}
          </label>
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
