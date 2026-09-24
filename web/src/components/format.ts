export function formatQty(qty: number | null): string {
  if (qty === null) return '—'
  return Number.isInteger(qty) ? String(qty) : qty.toLocaleString('ru-RU', { maximumFractionDigits: 3 })
}
