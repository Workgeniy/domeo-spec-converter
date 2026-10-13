// Расчёт цен КП для живых итогов в интерфейсе. Зеркало core/app/export/kp.py и
// core/app/pricing/indexation.py — менять синхронно: Excel считает ядро, а здесь только предпросмотр.

import type { Indexation, KpSettings, SummaryItem } from './api'

export const DEFAULT_KP: KpSettings = {
  contract_number: '',
  contract_date: '',
  supplier_position: 'Генеральный директор',
  customer_position: 'Генеральный директор',
  vat_rate: 0.22,
  markup_percent: 0,
  margin_percent: 0,
  delivery_percent: 0,
  installation_percent: 0,
  round_to_ruble: false,
}

export const DEFAULT_INDEXATION: Indexation = { date: '', rates: {}, apply_to_kp: false }

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
  const multiplier = s.margin_percent == null ? 1 + s.markup_percent / 100 : 1 / (1 - s.margin_percent / 100)
  const sale = roundTo(base * multiplier * (1 + s.delivery_percent / 100), digits)
  const installation = withInstallation ? roundTo((sale * s.installation_percent) / 100, digits) : 0
  return { sale, installation, unitTotal: roundTo(sale + installation, digits) }
}

// ---------- индексация к дате поставки ----------

export function todayISO(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** Доля лет между датами по дням; в прошлое — ноль (цены задним числом не индексируем). */
export function yearsBetween(fromISO: string, toISO: string): number {
  const from = Date.parse(fromISO)
  const to = Date.parse(toISO)
  if (!Number.isFinite(from) || !Number.isFinite(to)) return 0
  return Math.max(0, (to - from) / 86_400_000 / 365.25)
}

/** Ставка раздела; если своей нет — общая (ключ «»); если и её нет — null. */
export function rateFor(section: string, rates: Record<string, number>): number | null {
  if (section in rates) return rates[section]
  const key = section.trim().toLowerCase()
  for (const [name, rate] of Object.entries(rates)) {
    if (name.trim().toLowerCase() === key) return rate
  }
  return '' in rates ? rates[''] : null
}

/** Цена к дате поставки: base × (1 + ставка/100) ^ (лет до даты). Без даты или ставки — как есть. */
export function indexedPrice(price: number, section: string, ix: Indexation, from = ix.base_date || todayISO()): number {
  if (!ix.date) return price
  const rate = rateFor(section, ix.rates)
  if (rate === null) return price
  return roundTo(price * (1 + rate / 100) ** yearsBetween(from, ix.date), 2)
}

type Row = Pick<SummaryItem, 'price' | 'qty'> & { installation?: boolean; section?: string }

/** Базовая цена строки для КП: проиндексированная, если так настроено. */
export function kpBase(row: Row, ix?: Indexation): number | null {
  if (row.price === null) return null
  return ix?.apply_to_kp ? indexedPrice(row.price, row.section ?? '', ix) : row.price
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

export function kpTotals(rows: Row[], s: KpSettings, ix?: Indexation): KpTotals {
  let goods = 0
  let installation = 0
  let priced = 0
  let mounted = 0
  for (const row of rows) {
    const withInstallation = row.installation ?? true
    if (withInstallation) mounted += 1
    const base = kpBase(row, ix)
    if (base === null || row.qty === null) continue
    const p = priceRow(base, s, withInstallation)
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
