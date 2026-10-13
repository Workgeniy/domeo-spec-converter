import type { ParsedDocument, UploadDetail, UploadInfo } from './api'
import { readOriginal, type OriginalFile } from './originals'
import { newId, useWorkspace } from './store'
import { useTemplates } from './templates'
import { DEFAULT_INDEXATION } from './kp'
import { createProject } from './projects'

export async function uploadedOriginal(info: UploadInfo, doc: ParsedDocument, choose: boolean, file?: File): Promise<OriginalFile> {
  const original: OriginalFile = { id: info.id, name: info.file_name, serverId: info.id }
  if (/\.xlsx$/i.test(info.file_name)) {
    try { original.templateId = await useTemplates.getState().add(file ?? await readOriginal(original), doc, choose) }
    catch (e) { original.warning = e instanceof Error ? e.message : String(e) }
  }
  return original
}
export async function openUpload(detail: UploadDetail): Promise<void> {
  if (!detail.document) throw new Error('Документ ещё не разобран.')
  const original = await uploadedOriginal(detail.info, detail.document, false)
  const template = useTemplates.getState().templates.find((t) => t.id === original.templateId)
  await createProject({ version: 1, title: detail.info.title || detail.document.title,
    documents: [{ id: newId(), loaded_at: detail.info.created_at, doc: detail.document,
      original: { id: detail.info.id, upload_id: detail.info.id, name: detail.info.file_name, content: '', warning: original.warning } }],
    kp: { ...useWorkspace.getState().kp, contract_number: '', contract_date: '' },
    indexation: DEFAULT_INDEXATION, template: template?.content ?? null, template_name: template?.name ?? 'Стандартная форма',
  })
}
