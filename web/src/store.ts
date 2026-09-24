// Рабочее пространство объекта: несколько разобранных томов, правки менеджера к своду и
// параметры КП. Хранится в localStorage, чтобы перезагрузка страницы не теряла работу.

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { KpSettings, ParsedDocument, SummaryItem } from './api'
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
      // Правила расчёта и должности — свои у компании, они переживают смену объекта;
      // сбрасываются только данные конкретного объекта (договор).
      clear: () => set((s) => ({ title: '', documents: [], kp: { ...s.kp, contract_number: '', contract_date: '' } })),
    }),
    {
      name: 'domeo-spec-workspace',
      version: 4,
      migrate: (persisted, version) => {
        const state = persisted as Partial<WorkspaceState>
        if (version < 4) {
          // До v4 параметры КП описывали титульный лист (номер, дата, стороны, условия), которого
          // больше нет; переносим только то, что осталось в форме приложений к договору.
          const old = (state.kp ?? {}) as Partial<KpSettings> & {
            supplier?: { position?: string }
            customer?: { position?: string }
          }
          const kp: KpSettings = {
            ...DEFAULT_KP,
            contract_number: old.contract_number ?? '',
            contract_date: old.contract_date ?? '',
            supplier_position: old.supplier_position || old.supplier?.position || DEFAULT_KP.supplier_position,
            customer_position: old.customer_position || old.customer?.position || DEFAULT_KP.customer_position,
            vat_rate: old.vat_rate ?? DEFAULT_KP.vat_rate,
            markup_percent: old.markup_percent ?? 0,
            delivery_percent: old.delivery_percent ?? 0,
            installation_percent: old.installation_percent ?? 0,
            round_to_ruble: old.round_to_ruble ?? false,
          }
          return { ...state, kp }
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
