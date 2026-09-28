import type { ExportKind, Indexation, KpSettings, ParsedDocument, SummaryItem } from './api'
import type { SummaryRow, WorkspaceDocument } from './store'

/** Строка свода без клиентских пометок — в том виде, в каком её понимает ядро. */
function toSummaryItem(row: SummaryRow): SummaryItem {
  const { excluded: _excluded, ...item } = row
  // Строки, разобранные до появления новых полей, получают значения по умолчанию.
  return {
    ...item,
    installation: item.installation ?? true,
    price_source: item.price_source ?? '',
    history: item.history ?? null,
    internet: item.internet ?? null,
    internet_price: item.internet_price ?? null,
    internet_source: item.internet_source ?? '',
    internet_date: item.internet_date ?? '',
  }
}

/**
 * Документ для выгрузки: правки применены, исключённые строки убраны. kp — приложения к договору
 * по образцу (листы «1» и «2»), cost — себестоимость для Домео, working — рабочая выгрузка.
 * Несколько томов одного объекта склеиваются в один документ.
 */
export function buildExportRequest(title: string, documents: WorkspaceDocument[], kp: KpSettings, kind: ExportKind, indexation?: Indexation): ParsedDocument {
  const keep = (doc: WorkspaceDocument) => doc.doc.summary.filter((r) => !r.excluded).map(toSummaryItem)
  const settings = kind === 'kp' ? kp : null
  // Индексация уходит в ядро только с датой поставки; ставки — копия справочника на момент выгрузки.
  const dated = indexation && indexation.date ? indexation : null

  if (documents.length === 1) {
    const d = documents[0].doc
    return { ...d, title: title || d.title, summary: keep(documents[0]), kp: settings, kind, indexation: dated }
  }

  const codes = documents.map((d) => d.doc.doc_code || d.doc.file_name)
  return {
    // Имя файла выгрузки — по объекту; расширение нужно, чтобы ядро не приняло точку в названии за суффикс.
    file_name: `${sanitizeFileName(title || codes.join(' + '))}.xlsx`,
    doc_code: codes.join(', '),
    title,
    spec_title: '',
    pages: [],
    items: documents.flatMap((d) => d.doc.items),
    summary: documents.flatMap(keep),
    warnings: [],
    documents: documents.flatMap((d) => d.doc.documents),
    kp: settings,
    kind,
    indexation: dated,
  }
}

export function sanitizeFileName(name: string): string {
  return name.replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120) || 'спецификация'
}

export function downloadBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  a.click()
  URL.revokeObjectURL(url)
}
