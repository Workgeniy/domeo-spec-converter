// Клиент HTTP API (ASP.NET Core, api/). Ответы — в конверте { success, data, message, errors },
// ошибки — RFC 7807 ProblemDetails. Типы документа повторают доменную модель
// api/src/DomeoSpec.Domain/Specifications/ParsedDocument.cs (JSON в snake_case).

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
  engine: { available: boolean; ocr: string | null }
}

interface ApiResponse<T> {
  success: boolean
  data: T
  message?: string
  errors: string[]
}

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
    if (typeof body?.title === 'string') return body.title
  } catch {
    // тело не JSON — вернём статус
  }
  return `Ошибка ${response.status}`
}

async function readData<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as ApiResponse<T>
  return body.data
}

export function getHealth(): Promise<Health> {
  return fetch('/api/health').then((r) => readData<Health>(r))
}

export function parsePdf(file: File): Promise<ParsedDocument> {
  const form = new FormData()
  form.append('file', file)
  return fetch('/api/specifications/parse', { method: 'POST', body: form }).then((r) => readData<ParsedDocument>(r))
}

export async function exportExcel(doc: ParsedDocument): Promise<{ blob: Blob; fileName: string }> {
  const r = await fetch('/api/specifications/export', {
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
