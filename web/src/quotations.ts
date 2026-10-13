import { readData, type Indexation, type KpSettings, type ParsedDocument } from './api'
import { readOriginal } from './originals'
import { newId, useWorkspace, type WorkspaceDocument } from './store'
import { useTemplates } from './templates'
import { todayISO } from './kp'
import { editQuotation, flushProject } from './projects'

export interface QuotationInfo {
  id: string; project_id: string; parent_id: string | null; created_at: string; title: string
  contract_number: string; positions: number; margin_percent: number | null; template_name: string; file_name: string
}
interface ArchivedOriginal { id: string; name: string; content: string; upload_id?: string; template_id?: string; warning?: string }
export interface Snapshot {
  version: number; title: string; kp: KpSettings; indexation: Indexation; template: string | null; template_name: string
  documents: { id: string; loaded_at: string; doc: ParsedDocument; original: ArchivedOriginal | null }[]
}
export interface QuotationDetail { info: QuotationInfo; snapshot: Snapshot }
const URL = '/api/specifications/quotations'
export function listQuotations(search: string, offset: number, projectId?: string): Promise<QuotationInfo[]> {
  const query = new URLSearchParams({ search, offset: String(offset), limit: '31' })
  if (projectId) query.set('projectId', projectId)
  return fetch(`${URL}?${query}`).then(readData<QuotationInfo[]>)
}
export function getQuotation(id: string): Promise<QuotationDetail> {
  return fetch(`${URL}/${encodeURIComponent(id)}`).then(readData<QuotationDetail>)
}
export async function downloadQuotation(info: QuotationInfo): Promise<Blob> {
  const response = await fetch(`${URL}/${encodeURIComponent(info.id)}/file`)
  if (!response.ok) { await readData(response); throw new Error('Не удалось скачать КП.') }
  return response.blob()
}
function base64(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1])
    reader.onerror = () => reject(new Error('Не удалось прочитать исходный файл для истории.'))
    reader.readAsDataURL(file)
  })
}
// Повтор того же запроса после обрыва связи сохраняет один идентификатор, а не два КП.
let retry: { key: string; id: string } | null = null
export async function saveQuotation(documents: WorkspaceDocument[]): Promise<QuotationInfo> {
  await flushProject()
  const state = useWorkspace.getState()
  const templates = useTemplates.getState()
  const template = templates.templates.find((t) => t.id === templates.selected)
  const indexation = { ...state.indexation, base_date: state.indexation.base_date || todayISO() }
  const snapshot: Snapshot = {
    version: 1, title: state.title, kp: state.kp, indexation,
    template: template?.content ?? null, template_name: template?.name ?? 'Стандартная форма',
    documents: await Promise.all(documents.map(async (d) => ({
      id: d.id, loaded_at: d.loadedAt, doc: d.doc,
      original: d.original ? { id: d.original.id, name: d.original.name, warning: d.original.warning,
        template_id: d.original.templateId, upload_id: d.original.serverId, content: d.original.serverId ? '' : await base64(await readOriginal(d.original)) } : null,
    }))),
  }
  const body = { project_id: state.projectId, parent_id: state.quotationId, snapshot }
  const key = JSON.stringify(body)
  if (new Blob([key]).size > 95 * 1024 * 1024) throw new Error('Объект слишком большой для истории (лимит 95 МБ). Сформируйте КП по отдельному тому.')
  if (retry?.key !== key) retry = { key, id: newId() }
  const info = await fetch(URL, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, id: retry.id }) }).then(readData<QuotationInfo>)
  retry = null
  // Ответ от старого запроса не меняет объект, который пользователь уже закрыл или открыл заново.
  if (useWorkspace.getState().projectId === state.projectId && useWorkspace.getState().quotationId === state.quotationId) {
    useWorkspace.setState({ quotationId: info.id })
    if (useWorkspace.getState().indexation === state.indexation) useWorkspace.getState().setIndexation({ base_date: indexation.base_date })
  }
  return info
}
export async function openQuotation(detail: QuotationDetail): Promise<void> {
  await editQuotation(detail.snapshot, detail.info.project_id, detail.info.id)
}
