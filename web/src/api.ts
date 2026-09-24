// Клиент HTTP API бэкенда. Типы повторяют pydantic-модели server/app/models.py.

export interface SpecItem {
  id: number
  page: number
  pos: string
  pos_key: string
  name: string
  description: string
  type_mark: string
  code: string
  manufacturer: string
  unit: string
  qty: number | null
  qty_raw: string
  mass: string
  note: string
  group: string
  warnings: string[]
}

export interface GroupQty {
  group: string
  qty: number | null
}

export interface SummaryItem {
  pos: string
  pos_key: string
  name: string
  description: string
  type_mark: string
  manufacturer: string
  unit: string
  qty: number | null
  section: string
  note: string
  groups: GroupQty[]
  item_ids: number[]
  warnings: string[]
}

export interface PageInfo {
  number: number
  kind: 'spec' | 'other'
  source: 'text' | 'ocr' | 'skipped'
  rows: number
  warnings: string[]
}

export interface ParsedDocument {
  file_name: string
  doc_code: string
  title: string
  spec_title: string
  pages: PageInfo[]
  items: SpecItem[]
  summary: SummaryItem[]
  warnings: string[]
}

export interface Health {
  status: string
  ocr: string | null
}

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch {
    // тело не JSON — вернём статус
  }
  return `Ошибка ${response.status}`
}

export async function getHealth(): Promise<Health> {
  const r = await fetch('/api/health')
  if (!r.ok) throw new Error(await readError(r))
  return r.json()
}

export async function parsePdf(file: File): Promise<ParsedDocument> {
  const form = new FormData()
  form.append('file', file)
  const r = await fetch('/api/parse', { method: 'POST', body: form })
  if (!r.ok) throw new Error(await readError(r))
  return r.json()
}

export async function exportExcel(doc: ParsedDocument): Promise<{ blob: Blob; fileName: string }> {
  const r = await fetch('/api/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(doc),
  })
  if (!r.ok) throw new Error(await readError(r))
  const disposition = r.headers.get('Content-Disposition') ?? ''
  const match = /filename\*=UTF-8''([^;]+)/.exec(disposition)
  const fileName = match ? decodeURIComponent(match[1]) : 'спецификация.xlsx'
  return { blob: await r.blob(), fileName }
}
