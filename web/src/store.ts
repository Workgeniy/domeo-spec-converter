// Рабочее пространство объекта: несколько разобранных томов, правки менеджера к своду и
// параметры КП. Хранится в localStorage, чтобы перезагрузка страницы не теряла работу.

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { KpSettings, ParsedDocument, Party, SummaryItem } from './api'
import { DEFAULT_KP } from './kp'

/** Строка свода с клиентскими пометками, которых нет в модели ядра. */
export interface SummaryRow extends SummaryItem {
  /** Исключена из КП (например, «закупается образовательной организацией»). */
  excluded?: boolean
}

export interface WorkspaceDocument {
  id: string
  loadedAt: string
  doc: Omit<ParsedDocument, 'summary'> & { summary: SummaryRow[] }
}

export interface RowKey {
  docId: string
  index: number
}

export const rowKey = (k: RowKey) => `${k.docId}:${k.index}`

interface WorkspaceState {
  title: string
  documents: WorkspaceDocument[]
  kp: KpSettings
  setTitle: (title: string) => void
  addDocument: (doc: ParsedDocument) => void
  removeDocument: (id: string) => void
  updateRow: (key: RowKey, patch: Partial<SummaryRow>) => void
  updateRows: (keys: RowKey[], patch: Partial<SummaryRow>) => void
  setKp: (patch: Partial<KpSettings>) => void
  setKpParty: (side: 'supplier' | 'customer', patch: Partial<Party>) => void
  clear: () => void
}

function newId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function patchRows(documents: WorkspaceDocument[], keys: RowKey[], patch: Partial<SummaryRow>): WorkspaceDocument[] {
  const byDoc = new Map<string, Set<number>>()
  for (const k of keys) {
    if (!byDoc.has(k.docId)) byDoc.set(k.docId, new Set())
    byDoc.get(k.docId)!.add(k.index)
  }
  return documents.map((d) => {
    const indices = byDoc.get(d.id)
    if (!indices) return d
    return {
      ...d,
      doc: { ...d.doc, summary: d.doc.summary.map((row, i) => (indices.has(i) ? { ...row, ...patch } : row)) },
    }
  })
}

export const useWorkspace = create<WorkspaceState>()(
  persist(
    (set) => ({
      title: '',
      documents: [],
      kp: DEFAULT_KP,
      setTitle: (title) => set({ title }),
      addDocument: (doc) =>
        set((s) => ({
          // Название объекта берём из первого тома, если менеджер ещё ничего не ввёл.
          title: s.title || doc.title,
          documents: [...s.documents, { id: newId(), loadedAt: new Date().toISOString(), doc }],
        })),
      removeDocument: (id) => set((s) => ({ documents: s.documents.filter((d) => d.id !== id) })),
      updateRow: (key, patch) => set((s) => ({ documents: patchRows(s.documents, [key], patch) })),
      updateRows: (keys, patch) => set((s) => ({ documents: patchRows(s.documents, keys, patch) })),
      setKp: (patch) => set((s) => ({ kp: { ...s.kp, ...patch } })),
      setKpParty: (side, patch) => set((s) => ({ kp: { ...s.kp, [side]: { ...s.kp[side], ...patch } } })),
      // Реквизиты поставщика и правила расчёта — свои у компании, они переживают смену объекта;
      // сбрасываются только данные конкретного объекта.
      clear: () =>
        set((s) => ({
          title: '',
          documents: [],
          kp: { ...s.kp, number: '', customer: DEFAULT_KP.customer, contract_number: '', contract_date: '' },
        })),
    }),
    {
      name: 'domeo-spec-workspace',
      version: 3,
      migrate: (persisted, version) => {
        const state = persisted as Partial<WorkspaceState>
        if (version < 2) return { ...state, kp: DEFAULT_KP }
        if (version < 3 && state.kp) {
          // v2 хранил подписанта одной строкой (director); теперь только должность.
          const upgrade = (p: Partial<Party> & { director?: string }): Party => ({
            name: p.name ?? '',
            position: p.position || p.director || 'Генеральный директор',
            contacts: p.contacts ?? '',
          })
          return { ...state, kp: { ...state.kp, supplier: upgrade(state.kp.supplier), customer: upgrade(state.kp.customer) } }
        }
        return state
      },
      // localStorage может быть недоступен (приватный режим) — тогда работаем без сохранения.
      storage: {
        getItem: (name) => {
          try {
            const raw = localStorage.getItem(name)
            return raw ? JSON.parse(raw) : null
          } catch {
            return null
          }
        },
        setItem: (name, value) => {
          try {
            localStorage.setItem(name, JSON.stringify(value))
          } catch {
            // переполнение или запрет — правки живут только в памяти вкладки
          }
        },
        removeItem: (name) => {
          try {
            localStorage.removeItem(name)
          } catch {
            // ничего
          }
        },
      },
    },
  ),
)
