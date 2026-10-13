import { create } from 'zustand'
import { ApiError, getProject, putProject, type ProjectDetail, type SaveProject } from './api'
import { newId, useWorkspace } from './store'
import { useTemplates } from './templates'
import { restoreSnapshot, workspaceSnapshot } from './workspaceSnapshot'
import type { Snapshot } from './quotations'

type Status = 'idle' | 'pending' | 'saving' | 'saved' | 'error' | 'conflict'
export const useCloud = create<{ status: Status; error: string; busy: boolean }>(() => ({ status: 'idle', error: '', busy: true }))
let muted = false
let generation = 0
let timer: ReturnType<typeof setTimeout> | undefined
let running: Promise<void> | null = null
let pending: { projectId: string; generation: number; request: SaveProject } | null = null
let started = false

function schedule(delay = 1000) {
  clearTimeout(timer)
  timer = setTimeout(() => { void flushProject().catch(() => {}) }, delay)
}
function changed() {
  if (muted) return
  const s = useWorkspace.getState()
  if (!s.documents.length && !s.cloud.revision) return
  generation++
  useWorkspace.setState({ cloud: { ...s.cloud, dirty: true } })
  if (useCloud.getState().status === 'conflict') return
  useCloud.setState({ status: 'pending', error: '' })
  schedule()
}

/** Один запрос в полёте; правки во время запроса уходят следующей версией. */
export function flushProject(): Promise<void> {
  clearTimeout(timer)
  if (running) return running
  if (useCloud.getState().status === 'conflict') return Promise.reject(new Error(useCloud.getState().error))
  running = saveLoop().finally(() => { running = null })
  return running
}
async function saveLoop() {
  try {
    while (useWorkspace.getState().cloud.dirty) {
      useCloud.setState({ status: 'saving', error: '' })
      if (!pending) {
        const state = useWorkspace.getState()
        const stamp = generation
        const snapshot = await workspaceSnapshot(state)
        pending = { projectId: state.projectId, generation: stamp, request: {
          expected_revision: state.cloud.revision, mutation_id: newId(), snapshot, quotation_id: state.quotationId,
        } }
      }
      // При сбое повторяем именно прежний запрос, даже если пользователь уже продолжил править.
      const info = await putProject(pending.projectId, pending.request)
      if (useWorkspace.getState().projectId !== pending.projectId) throw new Error('Рабочий объект был переключён во время сохранения.')
      const dirty = generation !== pending.generation
      useWorkspace.setState({ cloud: { revision: info.revision, updatedAt: info.updated_at, dirty } })
      pending = null
    }
    useCloud.setState({ status: useWorkspace.getState().cloud.revision ? 'saved' : 'idle', error: '' })
  } catch (e) {
    const conflict = e instanceof ApiError && e.status === 409
    useCloud.setState({ status: conflict ? 'conflict' : 'error', error: e instanceof Error ? e.message : String(e) })
    if (!conflict && (!(e instanceof ApiError) || e.status >= 500)) schedule(15000)
    throw e
  }
}

async function apply(detail: ProjectDetail) {
  const s = detail.snapshot
  muted = true
  try {
    const documents = await restoreSnapshot(s)
    useWorkspace.setState({ title: s.title, documents, kp: s.kp, indexation: s.indexation,
      projectId: detail.info.id, quotationId: detail.info.quotation_id,
      cloud: { revision: detail.info.revision, dirty: false, updatedAt: detail.info.updated_at } })
    pending = null
    generation++
    useCloud.setState({ status: 'saved', error: '' })
  } finally { muted = false }
}

/** Переключение разрешено только после подтверждённого сервером сохранения текущих правок. */
export async function switchWorkspace(action: () => Promise<void>) {
  if (useCloud.getState().busy) throw new Error('Дождитесь открытия объекта.')
  useCloud.setState({ busy: true })
  try { await flushProject(); await action() }
  finally { useCloud.setState({ busy: false }) }
}
export async function openProject(id: string) { await switchWorkspace(async () => apply(await getProject(id))) }
export async function createProject(snapshot: Snapshot) {
  await switchWorkspace(async () => {
    await apply({ snapshot, info: { id: newId(), revision: 0, updated_at: '', title: snapshot.title,
      documents: snapshot.documents.length, positions: 0, margin_percent: snapshot.kp.margin_percent, quotation_id: null } })
    changed()
    await flushProject()
  })
}
export async function closeProject() {
  await switchWorkspace(async () => {
    muted = true
    try { useWorkspace.getState().clear(); useTemplates.getState().select(''); pending = null; generation++ }
    finally { muted = false }
    useCloud.setState({ status: 'idle', error: '' })
  })
}

// Историческую версию загружаем в рабочий объект с его актуальной базовой ревизией.
// Последующая запись всё равно отклонится, если за время открытия объект кто-то изменит.
export async function editQuotation(snapshot: Snapshot, projectId: string, quotationId: string) {
  await switchWorkspace(async () => {
    let current: ProjectDetail | null = null
    try { current = await getProject(projectId) } catch (e) { if (!(e instanceof ApiError && e.status === 404)) throw e }
    await apply({ snapshot, info: { id: projectId, revision: current?.info.revision ?? 0, updated_at: current?.info.updated_at ?? '',
      title: snapshot.title, documents: snapshot.documents.length, positions: 0, margin_percent: snapshot.kp.margin_percent, quotation_id: quotationId } })
    changed()
    await flushProject()
  })
}

/** При конфликте новый UUID сохраняет обе независимые работы. Старый объект не меняется. */
export async function saveProjectCopy() {
  if (useCloud.getState().busy) return
  useCloud.setState({ busy: true })
  try {
    if (running) { try { await running } catch { /* Копия разрешена после завершения неудачной записи. */ } }
    clearTimeout(timer)
    muted = true
    try {
      useWorkspace.setState({ projectId: newId(), quotationId: null, title: `${useWorkspace.getState().title.slice(0, 990)} — копия`,
        cloud: { revision: 0, dirty: true, updatedAt: '' } })
      pending = null; generation++
    } finally { muted = false }
    useCloud.setState({ status: 'pending', error: '' })
    await flushProject()
  } finally { useCloud.setState({ busy: false }) }
}
export async function retryProject() {
  const s = useWorkspace.getState()
  if (s.cloud.dirty || pending || !s.cloud.revision) return flushProject()
  useCloud.setState({ busy: true })
  try { await apply(await getProject(s.projectId)) }
  finally { useCloud.setState({ busy: false }) }
}
export async function reloadProject() {
  if (!window.confirm('Заменить правки этой вкладки сохранённым объектом? Чтобы оставить оба варианта, сначала сохраните отдельную копию.')) return
  useCloud.setState({ busy: true })
  try {
    if (running) { try { await running } catch { /* Получаем актуальный объект после завершения записи. */ } }
    clearTimeout(timer)
    await apply(await getProject(useWorkspace.getState().projectId))
  } finally { useCloud.setState({ busy: false }) }
}

export async function startAutosave() {
  if (started) return
  started = true
  useWorkspace.subscribe((s, previous) => {
    if (s.documents !== previous.documents || s.title !== previous.title || s.kp !== previous.kp ||
        s.indexation !== previous.indexation || s.quotationId !== previous.quotationId) changed()
  })
  useTemplates.subscribe((s, previous) => {
    const selected = s.templates.find((t) => t.id === s.selected)
    const old = previous.templates.find((t) => t.id === previous.selected)
    if (selected?.content !== old?.content || selected?.name !== old?.name) changed()
  })
  window.addEventListener('online', () => { if (useWorkspace.getState().cloud.dirty) schedule(0) })
  window.addEventListener('beforeunload', (event) => {
    if (useWorkspace.getState().cloud.dirty) { event.preventDefault(); event.returnValue = '' }
  })
  const s = useWorkspace.getState()
  try {
    if (s.cloud.revision && !s.cloud.dirty) await apply(await getProject(s.projectId))
    else if (s.documents.length || s.cloud.dirty) { changed(); await flushProject() }
  } catch (e) {
    if (useCloud.getState().status !== 'conflict') useCloud.setState({ status: 'error', error: e instanceof Error ? e.message : String(e) })
  } finally { useCloud.setState({ busy: false }) }
}
