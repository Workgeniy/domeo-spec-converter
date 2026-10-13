// Рабочее пространство объекта: несколько разобранных томов, правки менеджера к своду и
// параметры КП. Хранится в localStorage, чтобы перезагрузка страницы не теряла работу.

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { HistoryPrice, Indexation, InternetLookup, InternetOffer, KpSettings, ParsedDocument, PriceSource, SummaryItem } from './api'
import { DEFAULT_INDEXATION, DEFAULT_KP } from './kp'
import { forgetOriginal, type OriginalFile } from './originals'

/** Строка свода с клиентскими пометками, которых нет в модели ядра. */
export interface SummaryRow extends SummaryItem {
  /** Исключена из КП (например, «закупается образовательной организацией»). */
  excluded?: boolean
}

export interface WorkspaceDocument {
  id: string
  original?: OriginalFile
  loadedAt: string
  doc: Omit<ParsedDocument, 'summary'> & { summary: SummaryRow[] }
}

export interface RowKey {
  docId: string
  index: number
}

export const rowKey = (k: RowKey) => `${k.docId}:${k.index}`

export const useLocalPersistence = create<{ failed: boolean }>(() => ({ failed: false }))

export interface WorkspaceState {
  cloud: { revision: number; dirty: boolean; updatedAt: string }
  projectId: string
  quotationId: string | null
  title: string
  documents: WorkspaceDocument[]
  kp: KpSettings
  /** Индексация к дате поставки: дата — у объекта, ставки — копия справочника с сервера. */
  indexation: Indexation
  setIndexation: (patch: Partial<Indexation>) => void
  setTitle: (title: string) => void
  addDocument: (doc: ParsedDocument, original?: OriginalFile) => void
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

/** Картинка из интернета — только как запасная: если у позиции нет своей из файла. */
function internetImage(row: SummaryRow, lookup: InternetLookup): Partial<SummaryRow> {
  if (row.image && row.image_origin !== 'internet') return {} // своя картинка из файла — не трогаем
  if (lookup.status === 'found' && lookup.image) return { image: lookup.image, image_origin: 'internet' }
  if (row.image_origin === 'internet') return { image: '', image_origin: '' } // прежняя интернет-картинка устарела
  return {}
}

function withLookup(row: SummaryRow, lookup: InternetLookup): SummaryRow {
  // Ошибка поиска не стирает прежний удачный результат — оператор увидит её в сводке панели.
  if (lookup.status === 'error' && row.internet && row.internet.status !== 'error') return row
  if (lookup.status !== 'found') {
    // Цена с рынка пропала; базовая, взятая из неё, остаётся числом, но уже «вручную» — источника у неё больше нет.
    const source = row.price_source === 'internet' ? 'manual' : row.price_source
    return { ...row, internet: lookup, internet_price: null, internet_source: '', internet_date: lookup.looked_up_at, price_source: source, ...internetImage(row, lookup) }
  }
  const offer = offerForPrice(lookup)
  const price = lookup.price ?? offer?.price ?? null
  const next: SummaryRow = { ...row, internet: lookup, internet_price: price, internet_source: offer?.url ?? '', internet_date: lookup.looked_up_at, ...internetImage(row, lookup) }
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

export function newId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 15) | 64
  bytes[8] = (bytes[8] & 63) | 128
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
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
      cloud: { revision: 0, dirty: false, updatedAt: '' },
      projectId: newId(),
      quotationId: null,
      title: '',
      documents: [],
      kp: DEFAULT_KP,
      indexation: DEFAULT_INDEXATION,
      setIndexation: (patch) => set((s) => ({ indexation: { ...s.indexation, ...patch } })),
      setTitle: (title) => set({ title }),
      addDocument: (doc, original) =>
        set((s) => ({
          // Название объекта берём из первого тома, если менеджер ещё ничего не ввёл.
          title: s.title || doc.title,
          documents: [...s.documents, { id: newId(), loadedAt: new Date().toISOString(), doc, original }],
        })),
      removeDocument: (id) => set((s) => {
        const original = s.documents.find((d) => d.id === id)?.original
        if (original && !original.serverId) void forgetOriginal(original.id).catch(() => {})
        return { documents: s.documents.filter((d) => d.id !== id) }
      }),
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
      clear: () => {
        for (const d of useWorkspace.getState().documents) {
          if (d.original && !d.original.serverId) void forgetOriginal(d.original.id).catch(() => {})
        }
        set((s) => ({
          projectId: newId(),
          cloud: { revision: 0, dirty: false, updatedAt: '' },
          quotationId: null,
          title: '',
          documents: [],
          kp: { ...s.kp, contract_number: '', contract_date: '' },
          indexation: { ...s.indexation, date: '', base_date: '', apply_to_kp: false },
        }))
      },
    }),
    {
      name: 'domeo-spec-workspace',
      version: 10,
      migrate: (persisted, version) => {
        let state = persisted as Partial<WorkspaceState>
        if (version < 10) state = { ...state, cloud: { revision: 0, dirty: !!state.documents?.length, updatedAt: '' } }
        if (version < 9) {
          state = { ...state, projectId: state.projectId || newId(), quotationId: null,
            kp: { ...DEFAULT_KP, ...state.kp, margin_percent: null } }
        }
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
            margin_percent: old.margin_percent ?? null,
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
            useLocalPersistence.setState({ failed: false })
          } catch {
            useLocalPersistence.setState({ failed: true })
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
