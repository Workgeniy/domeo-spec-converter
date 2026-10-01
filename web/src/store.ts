// Рабочее пространство объекта: несколько разобранных томов, правки менеджера к своду и
// параметры КП. Хранится в localStorage, чтобы перезагрузка страницы не теряла работу.

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { HistoryPrice, Indexation, InternetLookup, InternetOffer, KpSettings, ParsedDocument, PriceSource, SummaryItem } from './api'
import { DEFAULT_INDEXATION, DEFAULT_KP } from './kp'

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
  /** Индексация к дате поставки: дата — у объекта, ставки — копия справочника с сервера. */
  indexation: Indexation
  setIndexation: (patch: Partial<Indexation>) => void
  setTitle: (title: string) => void
  addDocument: (doc: ParsedDocument) => void
  removeDocument: (id: string) => void
  updateRow: (key: RowKey, patch: Partial<SummaryRow>) => void
  updateRows: (keys: RowKey[], patch: Partial<SummaryRow>) => void
  /** Результаты сопоставления: ключ строки (docId:index) → результат. */
  applyMatches: (matches: Record<string, HistoryPrice>) => void
  /** Взять в базовую цену эталон из истории у выбранных строк (где есть сопоставление). */
  chooseHistoryPrice: (keys: RowKey[], which: HistoryChoice) => void
  /** Результаты поиска в интернете: ключ строки (docId:index) → результат. */
  applyInternet: (lookups: Record<string, InternetLookup>) => void
  /** Взять в базовую цену цену из интернета у выбранных строк (где она найдена). */
  chooseInternetPrice: (keys: RowKey[]) => void
  /** Сделать ценой из интернета другое предложение из найденных. */
  chooseOffer: (key: RowKey, offer: InternetOffer) => void
  setKp: (patch: Partial<KpSettings>) => void
  clear: () => void
}

/** Предложение, из которого взята рекомендуемая цена: точное с той же ценой, иначе первое. */
function offerForPrice(lookup: InternetLookup): InternetOffer | undefined {
  if (lookup.price === null) return lookup.offers[0]
  return lookup.offers.find((o) => !o.analog && o.price === lookup.price) ?? lookup.offers.find((o) => o.price === lookup.price) ?? lookup.offers[0]
}

function withLookup(row: SummaryRow, lookup: InternetLookup): SummaryRow {
  // Ошибка поиска не стирает прежний удачный результат — оператор увидит её в сводке панели.
  if (lookup.status === 'error' && row.internet && row.internet.status !== 'error') return row
  if (lookup.status !== 'found') {
    // Цена с рынка пропала; базовая, взятая из неё, остаётся числом, но уже «вручную» — источника у неё больше нет.
    const source = row.price_source === 'internet' ? 'manual' : row.price_source
    return { ...row, internet: lookup, internet_price: null, internet_source: '', internet_date: lookup.looked_up_at, price_source: source }
  }
  const offer = offerForPrice(lookup)
  const price = lookup.price ?? offer?.price ?? null
  const next: SummaryRow = { ...row, internet: lookup, internet_price: price, internet_source: offer?.url ?? '', internet_date: lookup.looked_up_at }
  // Если базовая цена уже взята из интернета — она следует за свежим результатом.
  return row.price_source === 'internet' && price !== null ? { ...next, price } : next
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

function patchRowsWith(documents: WorkspaceDocument[], key: RowKey, update: (row: SummaryRow) => SummaryRow): WorkspaceDocument[] {
  return documents.map((d) =>
    d.id !== key.docId ? d : { ...d, doc: { ...d.doc, summary: d.doc.summary.map((row, i) => (i === key.index ? update(row) : row)) } },
  )
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
      indexation: DEFAULT_INDEXATION,
      setIndexation: (patch) => set((s) => ({ indexation: { ...s.indexation, ...patch } })),
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
      applyInternet: (lookups) =>
        set((s) => ({
          documents: s.documents.map((d) => ({
            ...d,
            doc: {
              ...d.doc,
              summary: d.doc.summary.map((row, i) => {
                const lookup = lookups[`${d.id}:${i}`]
                return lookup ? withLookup(row, lookup) : row
              }),
            },
          })),
        })),
      chooseInternetPrice: (keys) =>
        set((s) => {
          const wanted = new Set(keys.map(rowKey))
          return {
            documents: s.documents.map((d) => ({
              ...d,
              doc: {
                ...d.doc,
                summary: d.doc.summary.map((row, i) => {
                  if (!wanted.has(`${d.id}:${i}`)) return row
                  const price = row.internet_price ?? null
                  return price === null ? row : { ...row, price, price_source: 'internet' }
                }),
              },
            })),
          }
        }),
      chooseOffer: (key, offer) =>
        set((s) => ({
          documents: patchRowsWith(s.documents, key, (row) => ({
            ...row,
            internet_price: offer.price,
            internet_source: offer.url,
            internet_date: row.internet?.looked_up_at || row.internet_date,
            ...(row.price_source === 'internet' ? { price: offer.price } : {}),
          })),
        })),
      setKp: (patch) => set((s) => ({ kp: { ...s.kp, ...patch } })),
      // Правила расчёта и должности — свои у компании, они переживают смену объекта;
      // сбрасываются только данные конкретного объекта (договор).
      // Дата поставки — у объекта, ставки индексации — справочник компании, остаются.
      clear: () =>
        set((s) => ({
          title: '',
          documents: [],
          kp: { ...s.kp, contract_number: '', contract_date: '' },
          indexation: { ...s.indexation, date: '', apply_to_kp: false },
        })),
    }),
    {
      name: 'domeo-spec-workspace',
      version: 8,
      migrate: (persisted, version) => {
        let state = persisted as Partial<WorkspaceState>
        if (version < 8 && state.documents) {
          // v8: у строк свода появились параметры поиска от оператора, у результата поиска — с какими искали.
          state = {
            ...state,
            documents: state.documents.map((d) => ({
              ...d,
              doc: {
                ...d.doc,
                summary: d.doc.summary.map((row) => ({
                  ...row,
                  search_params: row.search_params ?? [],
                  internet: row.internet ? { ...row.internet, params: row.internet.params ?? [] } : (row.internet ?? null),
                })),
              },
            })),
          }
        }
        if (version < 7) {
          state = { ...state, indexation: state.indexation ?? DEFAULT_INDEXATION }
        }
        if (version < 6 && state.documents) {
          // v6: у строк свода появился результат поиска в интернете.
          state = {
            ...state,
            documents: state.documents.map((d) => ({
              ...d,
              doc: { ...d.doc, summary: d.doc.summary.map((row) => ({ internet: null, ...row })) },
            })),
          }
        }
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
