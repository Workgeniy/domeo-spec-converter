import { create } from 'zustand'
import { exportExcel } from './api'
import type { ParsedDocument } from './api'
import { DEFAULT_KP } from './kp'
import { newId, useWorkspace } from './store'

interface Template { id: string; name: string; content: string }
interface Templates {
  templates: Template[]
  selected: string
  select: (id: string) => void
  add: (file: File, document?: ParsedDocument, choose?: boolean) => Promise<string>
  restore: (content: string | null, name: string) => void
  remove: () => void
}

const STORAGE = 'domeo-kp-templates'
function saved(): { templates: Template[]; selected: string } {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE) ?? '{}')
    const templates = Array.isArray(value.templates) ? value.templates.filter((t: Template) => typeof t.id === 'string' && typeof t.name === 'string' && typeof t.content === 'string') : []
    return { templates, selected: templates.some((t: Template) => t.id === value.selected) ? value.selected : '' }
  } catch { return { templates: [], selected: '' } }
}
function save(templates: Template[], selected: string) {
  try { localStorage.setItem(STORAGE, JSON.stringify({ templates, selected })) }
  catch { throw new Error('Не удалось сохранить шаблоны в браузере. Освободите место или удалите ненужные шаблоны.') }
}

export const useTemplates = create<Templates>((set, get) => ({
  ...saved(),
  select: (selected) => { save(get().templates, selected); set({ selected }) },
  add: async (file, document, choose = true) => {
    const projectId = useWorkspace.getState().projectId
    if (!file.name.toLowerCase().endsWith('.xlsx')) throw new Error('Выберите шаблон в формате XLSX.')
    if (file.size > 2_000_000) throw new Error('Шаблон должен быть не больше 2 МБ.')
    const content = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result).split(',')[1])
      reader.onerror = () => reject(new Error('Не удалось прочитать файл шаблона.'))
      reader.readAsDataURL(file)
    })
    const selected = typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`
    // Проверяем форму на сервере до сохранения и выбора.
    const doc = document ?? useWorkspace.getState().documents.find((d) => d.doc.summary.length > 0)?.doc
    if (!doc) throw new Error('Сначала загрузите спецификацию с позициями.')
    await exportExcel({ ...doc, summary: doc.summary.slice(0, 1), items: [], pages: [], documents: [],
      kind: 'kp', kp: DEFAULT_KP, kp_template: content })
    const existing = get().templates.find((t) => t.content === content)
    const id = existing?.id ?? selected
    const templates = existing ? get().templates : [...get().templates, { id, name: file.name, content }]
    const nextSelected = choose && useWorkspace.getState().projectId === projectId ? id : get().selected
    save(templates, nextSelected)
    set({ templates, selected: nextSelected })
    return id
  },
  restore: (content, name) => {
    const existing = content ? get().templates.find((t) => t.content === content) : undefined
    const selected = content ? existing?.id ?? newId() : ''
    const templates = content && !existing ? [...get().templates, { id: selected, name, content }] : get().templates
    save(templates, selected)
    set({ templates, selected })
  },
  remove: () => {
    const templates = get().templates.filter((t) => t.id !== get().selected)
    save(templates, '')
    set({ templates, selected: '' })
  },
}))
