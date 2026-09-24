// Расчёт цен КП для живых итогов в интерфейсе. Зеркало core/app/export/kp.py —
// менять синхронно: Excel считает ядро, а здесь только предпросмотр.

import type { KpSettings, SummaryItem } from './api'

export const DEFAULT_KP: KpSettings = {
  number: '',
  date: new Date().toISOString().slice(0, 10),
  valid_days: 30,
  supplier: { name: '', position: 'Генеральный директор', signatory: '', contacts: '' },
  customer: { name: '', position: 'Генеральный директор', signatory: '', contacts: '' },
  contract_number: '',
  contract_date: '',
  vat_rate: 0.2,
  markup_percent: 0,
  installation_percent: 0,
  delivery_percent: 0,
  round_to_ruble: false,
  terms: '',
}

export interface RowPrice {
  /** Цена товара за единицу в КП, с НДС. */
  sale: number
  /** СМР за единицу, с НДС. */
  installation: number
  /** Цена за единицу вкл. СМР (графа M). */
  unitTotal: number
}

function roundTo(value: number, digits: number): number {
  const k = 10 ** digits
  return Math.round(value * k) / k
}

export function priceRow(base: number, s: KpSettings): RowPrice {
  const digits = s.round_to_ruble ? 0 : 2
  const sale = roundTo(base * (1 + s.markup_percent / 100), digits)
  const installation = roundTo((sale * s.installation_percent) / 100, digits)
  return { sale, installation, unitTotal: roundTo(sale + installation, digits) }
}

export interface KpTotals {
  positions: number
  priced: number
  goodsWithVat: number
  goodsWithoutVat: number
  vat: number
  installation: number
  delivery: number
  total: number
}

export function kpTotals(rows: Pick<SummaryItem, 'price' | 'qty'>[], s: KpSettings): KpTotals {
  let goods = 0
  let installation = 0
  let priced = 0
  for (const row of rows) {
    if (row.price === null || row.qty === null) continue
    const p = priceRow(row.price, s)
    priced += 1
    goods += p.sale * row.qty
    installation += p.installation * row.qty
  }
  const goodsWithoutVat = roundTo(goods / (1 + s.vat_rate), 2)
  const delivery = roundTo((goods * s.delivery_percent) / 100, 2)
  goods = roundTo(goods, 2)
  installation = roundTo(installation, 2)
  return {
    positions: rows.length,
    priced,
    goodsWithVat: goods,
    goodsWithoutVat,
    vat: roundTo(goods - goodsWithoutVat, 2),
    installation,
    delivery,
    total: roundTo(goods + installation + delivery, 2),
  }
}
