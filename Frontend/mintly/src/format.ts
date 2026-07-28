// "$1,234.56", or an em dash when there's no value
export function money(value?: number | null): string {
  return value != null
    ? `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—'
}

// Signed dollar amount with the sign before the $: "+$6.31" / "-$58.11" / "$0.00"
export function signedMoney(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}$${Math.abs(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}
