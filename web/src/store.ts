// Рабочее пространство объекта: несколько разобранных томов, правки менеджера к своду и
// параметры КП. Хранится в localStorage, чтобы перезагрузка страницы не теряла работу.

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { HistoryPrice, KpSettings, ParsedDocument, PriceSource, SummaryItem } from './api'
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
  /** Результаты сопоставления: ключ строки (docId:index) → результат. */
  applyMatches: (matches: Record<string, HistoryPrice>) => void
  /** Взять в базовую цену эталон из истории у выбранных строк (где есть сопоставление). */
  chooseHistoryPrice: (keys: RowKey[], which: HistoryChoice) => void
  setKp: (patch: Partial<KpSettings>) => void
  clear: () => void
}

export type HistoryChoice = 'min' | 'max' | 'median' | 'last'

const CHOICE_SOURCE: Record<HistoryChoice, PriceSource> = {
  min: 'history_min',
  max: 'history_max',
  median: 'history_median',
  last: 'history_last',
}

function historyPrice(row: SummaryRow, which: HistoryChoice): number | null {
  const best = row.history?.best
  if (!best) return null
  return { min: best.price_min, max: best.price_max, median: best.price_median, last: best.price_last }[which]
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
      applyMatches: (matches) =>
        set((s) => ({
          documents: s.documents.map((d) => ({
            ...d,
            doc: {
              ...d.doc,
              summary: d.doc.summary.map((row, i) => {
                const match = matches[`${d.id}:${i}`]
                return match ? { ...row, history: match } : row
              }),
            },
          })),
        })),
      chooseHistoryPrice: (keys, which) =>
        set((s) => {
          const wanted = new Set(keys.map(rowKey))
          return {
            documents: s.documents.map((d) => ({
              ...d,
              doc: {
                ...d.doc,
                summary: d.doc.summary.map((row, i) => {
                  if (!wanted.has(`${d.id}:${i}`)) return row
                  const price = historyPrice(row, which)
                  return price === null ? row : { ...row, price, price_source: CHOICE_SOURCE[which] }
                }),
              },
            })),
          }
        }),
      setKp: (patch) => set((s) => ({ kp: { ...s.kp, ...patch } })),
      // Правила расчёта и должности — свои у компании, они переживают смену объекта;
      // сбрасываются только данные конкретного объекта (договор).
      clear: () => set((s) => ({ title: '', documents: [], kp: { ...s.kp, contract_number: '', contract_date: '' } })),
    }),
    {
      name: 'domeo-spec-workspace',
      version: 5,
      migrate: (persisted, version) => {
        let state = persisted as Partial<WorkspaceState>
        if (version < 5 && state.documents) {
          // v5: у строк свода появились источник цены, сопоставление с историей и цена из интернета.
          state = {
            ...state,
            documents: state.documents.map((d) => ({
              ...d,
              doc: {
                ...d.doc,
                summary: d.doc.summary.map((row) => ({
                  price_source: row.price !== null && row.price !== undefined ? 'manual' : '',
                  history: null,
                  internet_price: null,
                  internet_source: '',
                  internet_date: '',
                  installation: true,
                  ...row,
                })),
              },
            })),
          }
        }
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
