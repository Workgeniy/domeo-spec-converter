// Сравнение двух версий спецификации: что добавлено, удалено, изменено. Позиции сопоставляются
// по номеру (заказчик правит ячейки, нумерация обычно та же); несопоставленный остаток —
// подхват по наименованию, чтобы перенумерованную позицию не показать как удаление+добавление.

import type { SummaryItem } from './api'

export type DiffStatus = 'added' | 'removed' | 'changed' | 'unchanged'
export type DiffField = 'pos' | 'name' | 'description' | 'type_mark' | 'unit' | 'qty'

export interface FieldChange {
  field: DiffField
  label: string
  before: string
  after: string
}

export interface DiffRow {
  status: DiffStatus
  pos: string
  name: string
  before: SummaryItem | null
  after: SummaryItem | null
  changes: FieldChange[]
}

export interface SpecDiff {
  rows: DiffRow[]
  counts: Record<DiffStatus, number>
}

const FIELDS: { field: DiffField; label: string; get: (s: SummaryItem) => string }[] = [
  { field: 'name', label: 'Наименование', get: (s) => s.name },
  { field: 'description', label: 'Характеристики', get: (s) => s.description },
  { field: 'type_mark', label: 'Тип, марка', get: (s) => s.type_mark },
  { field: 'unit', label: 'Ед.', get: (s) => s.unit },
  { field: 'qty', label: 'Кол-во', get: (s) => qtyText(s.qty) },
]

const norm = (s: string) => (s || '').replace(/\s+/g, ' ').trim()
const qtyText = (q: number | null) => (q == null ? '' : String(q))
const posKey = (s: SummaryItem) => norm(s.pos_key) || norm(s.pos)

/** Ключ по наименованию для подхвата несопоставленных: строчные, ё→е, без пунктуации. */
const nameKey = (s: SummaryItem) =>
  (s.description || s.name).toLowerCase().replace(/ё/g, 'е').replace(/[^a-zа-я0-9]+/g, ' ').trim()

function push(map: Map<string, SummaryItem[]>, key: string, item: SummaryItem) {
  const list = map.get(key)
  if (list) list.push(item)
  else map.set(key, [item])
}

function fieldChanges(before: SummaryItem, after: SummaryItem): FieldChange[] {
  const changes: FieldChange[] = []
  for (const f of FIELDS) {
    const b = f.get(before)
    const a = f.get(after)
    if (norm(b) !== norm(a)) changes.push({ field: f.field, label: f.label, before: b, after: a })
  }
  return changes
}

function matchedRow(before: SummaryItem, after: SummaryItem): DiffRow {
  const changes = fieldChanges(before, after)
  if (norm(before.pos) !== norm(after.pos)) {
    changes.unshift({ field: 'pos', label: '№ позиции', before: before.pos, after: after.pos })
  }
  return {
    status: changes.length ? 'changed' : 'unchanged',
    pos: after.pos || before.pos,
    name: after.name || before.name,
    before,
    after,
    changes,
  }
}

/** Естественная сортировка номеров позиций: «2.9» < «2.10». */
function comparePos(a: string, b: string): number {
  const pa = a.match(/\d+|\D+/g) ?? []
  const pb = b.match(/\d+|\D+/g) ?? []
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] ?? ''
    const y = pb[i] ?? ''
    const nx = Number(x)
    const ny = Number(y)
    const cmp = !isNaN(nx) && !isNaN(ny) ? nx - ny : x.localeCompare(y, 'ru')
    if (cmp) return cmp
  }
  return 0
}

export function diffSpecs(before: SummaryItem[], after: SummaryItem[]): SpecDiff {
  const beforeByPos = new Map<string, SummaryItem[]>()
  for (const s of before) push(beforeByPos, posKey(s), s)
  const afterByPos = new Map<string, SummaryItem[]>()
  for (const s of after) push(afterByPos, posKey(s), s)

  const rows: DiffRow[] = []
  const usedBefore = new Set<SummaryItem>()
  const usedAfter = new Set<SummaryItem>()

  // 1) сопоставление по номеру позиции (попарно внутри одного номера, обычно 1:1)
  for (const [key, afterItems] of afterByPos) {
    const beforeItems = key ? beforeByPos.get(key) : undefined
    if (!beforeItems) continue
    const n = Math.min(beforeItems.length, afterItems.length)
    for (let i = 0; i < n; i++) {
      rows.push(matchedRow(beforeItems[i], afterItems[i]))
      usedBefore.add(beforeItems[i])
      usedAfter.add(afterItems[i])
    }
  }

  // 2) остаток — подхват по наименованию (перенумерованная позиция = «изменено», не +/-)
  const afterByName = new Map<string, SummaryItem[]>()
  for (const s of after) if (!usedAfter.has(s)) push(afterByName, nameKey(s), s)
  for (const b of before) {
    if (usedBefore.has(b)) continue
    const key = nameKey(b)
    const match = key.length >= 3 ? afterByName.get(key)?.find((s) => !usedAfter.has(s)) : undefined
    if (match) {
      rows.push(matchedRow(b, match))
      usedBefore.add(b)
      usedAfter.add(match)
    }
  }

  // 3) оставшиеся: только в старой — удалено, только в новой — добавлено
  for (const b of before) {
    if (usedBefore.has(b)) continue
    rows.push({ status: 'removed', pos: b.pos, name: b.name, before: b, after: null, changes: [] })
  }
  for (const a of after) {
    if (usedAfter.has(a)) continue
    rows.push({ status: 'added', pos: a.pos, name: a.name, before: null, after: a, changes: [] })
  }

  rows.sort((r1, r2) => comparePos(r1.pos, r2.pos))
  const counts: Record<DiffStatus, number> = { added: 0, removed: 0, changed: 0, unchanged: 0 }
  for (const r of rows) counts[r.status]++
  return { rows, counts }
}
