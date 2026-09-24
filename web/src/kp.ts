// Расчёт цен КП для живых итогов в интерфейсе. Зеркало core/app/export/kp.py —
// менять синхронно: Excel считает ядро, а здесь только предпросмотр.

import type { KpSettings, SummaryItem } from './api'

export const DEFAULT_KP: KpSettings = {
  contract_number: '',
  contract_date: '',
  supplier_position: 'Генеральный директор',
  customer_position: 'Генеральный директор',
  vat_rate: 0.2,
  markup_percent: 0,
  delivery_percent: 0,
  installation_percent: 0,
  round_to_ruble: false,
}

export interface RowPrice {
  /** Цена товара за единицу в КП, с НДС (доставка внутри). */
  sale: number
  /** СМР за единицу, с НДС; 0 для инвентаря без монтажа. */
  installation: number
  /** Цена за единицу вкл. СМР (графа M листа «1»). */
  unitTotal: number
}

function roundTo(value: number, digits: number): number {
  const k = 10 ** digits
  return Math.round(value * k) / k
}

export function priceRow(base: number, s: KpSettings, withInstallation = true): RowPrice {
  const digits = s.round_to_ruble ? 0 : 2
  const sale = roundTo(base * (1 + s.markup_percent / 100) * (1 + s.delivery_percent / 100), digits)
  const installation = withInstallation ? roundTo((sale * s.installation_percent) / 100, digits) : 0
  return { sale, installation, unitTotal: roundTo(sale + installation, digits) }
}

export interface KpTotals {
  positions: number
  /** Позиций на листе «1» (с монтажом) и «2» (инвентарь). */
  mounted: number
  inventory: number
  priced: number
  goodsWithVat: number
  goodsWithoutVat: number
  vat: number
  installation: number
  total: number
}

type Row = Pick<SummaryItem, 'price' | 'qty'> & { installation?: boolean }

export function kpTotals(rows: Row[], s: KpSettings): KpTotals {
  let goods = 0
  let installation = 0
  let priced = 0
  let mounted = 0
  for (const row of rows) {
    const withInstallation = row.installation ?? true
    if (withInstallation) mounted += 1
    if (row.price === null || row.qty === null) continue
    const p = priceRow(row.price, s, withInstallation)
    priced += 1
    goods += p.sale * row.qty
    installation += p.installation * row.qty
  }
  const goodsWithoutVat = roundTo(goods / (1 + s.vat_rate), 2)
  goods = roundTo(goods, 2)
  installation = roundTo(installation, 2)
  return {
    positions: rows.length,
    mounted,
    inventory: rows.length - mounted,
    priced,
    goodsWithVat: goods,
    goodsWithoutVat,
    vat: roundTo(goods - goodsWithoutVat, 2),
    installation,
    total: roundTo(goods + installation, 2),
  }
}
