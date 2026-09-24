export function formatQty(qty: number | null): string {
  if (qty === null) return '—'
  return Number.isInteger(qty) ? String(qty) : qty.toLocaleString('ru-RU', { maximumFractionDigits: 3 })
}

export function formatMoney(value: number | null): string {
  if (value === null) return '—'
  return value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** Сумма по строке: цена × количество, если и то и другое известно. */
export function rowTotal(qty: number | null, price: number | null): number | null {
  return qty === null || price === null ? null : qty * price
}
