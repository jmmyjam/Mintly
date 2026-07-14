// "$12.34", or an em dash when there's no value
export function money(value?: number | null): string {
  return value != null ? `$${value.toFixed(2)}` : '—'
}
