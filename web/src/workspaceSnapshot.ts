import { uploadSource } from './api'
import { forgetOriginal, readOriginal, rememberOriginal } from './originals'
import type { Snapshot } from './quotations'
import type { WorkspaceDocument, WorkspaceState } from './store'
import { useTemplates } from './templates'

const migrated = new Map<string, Promise<string>>()
/** Старые локальные исходники переносим один раз; повтор загрузки на сервере дедуплицируется. */
export async function workspaceSnapshot(state: WorkspaceState): Promise<Snapshot> {
  const templates = useTemplates.getState()
  const template = templates.templates.find((t) => t.id === templates.selected)
  const documents = await Promise.all(state.documents.map(async (d) => {
    const o = d.original
    let uploadId = o?.serverId
    if (o && !uploadId) {
      let pending = migrated.get(o.id)
      if (!pending) {
        pending = readOriginal(o).then((file) => uploadSource(file, state.projectId, state.title)).then((info) => info.id)
        migrated.set(o.id, pending)
        void pending.catch(() => migrated.delete(o.id))
      }
      uploadId = await pending
    }
    return { id: d.id, loaded_at: d.loadedAt, doc: d.doc,
      original: o ? { id: uploadId!, name: o.name, warning: o.warning, upload_id: uploadId, content: '' } : null }
  }))
  return { version: 1, title: state.title, kp: state.kp, indexation: state.indexation,
    template: template?.content ?? null, template_name: template?.name ?? 'Стандартная форма', documents }
}

export async function restoreSnapshot(s: Snapshot): Promise<WorkspaceDocument[]> {
  if (s.version !== 1) throw new Error('Версия объекта не поддерживается. Обновите приложение.')
  const created: string[] = []
  try {
    const documents: WorkspaceDocument[] = []
    for (const d of s.documents) {
      let original
      if (d.original?.upload_id) original = { id: d.original.upload_id, name: d.original.name,
        serverId: d.original.upload_id, warning: d.original.warning }
      else if (d.original) {
        const bytes = Uint8Array.from(atob(d.original.content), (c) => c.charCodeAt(0))
        original = { ...await rememberOriginal(new File([bytes], d.original.name)), warning: d.original.warning }
        created.push(original.id)
      }
      documents.push({ id: d.id, loadedAt: d.loaded_at, doc: d.doc, original })
    }
    useTemplates.getState().restore(s.template, s.template_name)
    return documents
  } catch (error) {
    await Promise.all(created.map((id) => forgetOriginal(id).catch(() => {})))
    throw error
  }
}
