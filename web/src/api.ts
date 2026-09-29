// Клиент HTTP API (ASP.NET Core, api/). Ответы — в конверте { success, data, message, errors },
// ошибки — RFC 7807 ProblemDetails. Типы документа повторяют доменную модель
// api/src/DomeoSpec.Domain/Specifications/ParsedDocument.cs (JSON в snake_case).

export interface SpecItem {
  id: number
  page: number
  pos: string
  pos_key: string
  name: string
  description: string
  type_mark: string
  code: string
  manufacturer: string
  unit: string
  qty: number | null
  qty_raw: string
  mass: string
  note: string
  group: string
  source_doc: string
  warnings: string[]
}

export interface GroupQty {
  group: string
  qty: number | null
}

/** Позиция прайса закупки, похожая на позицию спецификации. */
export interface HistoryCandidate {
  key: string
  name: string
  group: string
  /** 1.0 — точное совпадение наименования. */
  score: number
  /** Совпало не с нашим наименованием, а с названием у поставщика из истории закупок. */
  alias: string
  price_min: number | null
  price_max: number | null
  price_median: number | null
  price_last: number | null
  last_date: string | null
  purchases: number
  descriptions: string[]
}

/** Одна покупка из истории — чтобы оператор видел, откуда эталон. */
export interface HistoryPurchase {
  purchased_at: string | null
  unit_price: number
  qty: number
  partner_item: string
  order: string
  outlier: boolean
}

export type MatchKind = 'exact' | 'fuzzy' | 'analog' | 'none'

/** Результат сопоставления позиции с историей закупок. */
export interface HistoryPrice {
  kind: MatchKind
  best: HistoryCandidate | null
  candidates: HistoryCandidate[]
  purchases: HistoryPurchase[]
  matched_at: string
}

/** Одно предложение из интернета — где и почём нашлось. */
export interface InternetOffer {
  title: string
  url: string
  shop: string
  /** За единицу, руб. с НДС. */
  price: number
  /** Не та же позиция, а похожая. */
  analog: boolean
  note: string
}

export type InternetStatus = 'found' | 'not_found' | 'error'

/** Результат поиска цены в интернете на дату. */
export interface InternetLookup {
  status: InternetStatus
  query: string
  /** Дата, на которую найдена цена (ГГГГ-ММ-ДД). */
  looked_up_at: string
  offers: InternetOffer[]
  /** Рекомендуемая цена — типичная среди подходящих предложений. */
  price: number | null
  comment: string
  provider: string
  /** Сколько поисковых запросов ушло — для оценки расходов. */
  searches: number
}

/** Откуда взята базовая цена позиции. */
export type PriceSource = '' | 'manual' | 'history_min' | 'history_max' | 'history_median' | 'history_last' | 'internet'

export interface SummaryItem {
  pos: string
  pos_key: string
  name: string
  description: string
  type_mark: string
  manufacturer: string
  unit: string
  qty: number | null
  section: string
  note: string
  /** Базовая цена за единицу с НДС — выбранная оператором; null — не проставлена. */
  price: number | null
  price_source: PriceSource
  /** Сопоставление с историей закупок; null — ещё не сопоставляли. */
  history: HistoryPrice | null
  /** Поиск в интернете: предложения и рекомендуемая цена; null — ещё не искали. */
  internet: InternetLookup | null
  /** Цена из интернета на дату — выбранное предложение. */
  internet_price: number | null
  /** Ссылка на выбранное предложение. */
  internet_source: string
  internet_date: string
  /** Подлежит монтажу/пусконаладке → лист «1» (Приложение №1.1), иначе инвентарь → лист «2». */
  installation: boolean
  source_doc: string
  groups: GroupQty[]
  item_ids: number[]
  warnings: string[]
}

export interface PageInfo {
  number: number
  kind: 'spec' | 'other'
  source: 'text' | 'ocr' | 'skipped'
  rows: number
  warnings: string[]
}

/** Сводка по одному исходному PDF. */
export interface SourceDocument {
  doc_code: string
  file_name: string
  title: string
  spec_title: string
  pages_total: number
  spec_pages: number[]
  ocr_pages: number[]
  skipped_pages: number[]
  rows: number
  positions: number
  warnings: string[]
}

/** Параметры КП — приложений к договору по образцу; правила цены — в web/src/kp.ts (зеркало core/app/export/kp.py). */
export interface KpSettings {
  contract_number: string
  contract_date: string
  /** Должность подписанта поставщика в блоке подписей. */
  supplier_position: string
  customer_position: string
  vat_rate: number
  markup_percent: number
  /** Доставка — входит в цену товара. */
  delivery_percent: number
  /** СМР от цены товара — только для позиций с монтажом (лист «1»). */
  installation_percent: number
  round_to_ruble: boolean
}

export interface ParsedDocument {
  file_name: string
  doc_code: string
  title: string
  spec_title: string
  pages: PageInfo[]
  items: SpecItem[]
  summary: SummaryItem[]
  warnings: string[]
  documents: SourceDocument[]
  /** Только в запросе на выгрузку: параметры КП. */
  kp?: KpSettings | null
  /** Только в запросе на выгрузку: working — рабочая, kp — приложения к договору, cost — себестоимость. */
  kind?: ExportKind
  /** Только в запросе на выгрузку: индексация цен к дате поставки. */
  indexation?: Indexation | null
}

export type ExportKind = 'working' | 'kp' | 'cost'

/** Сводка по загруженному прайсу закупки. */
export interface PriceListInfo {
  source: string
  built_at: string
  rows_total: number
  entries: number
  with_two_or_more: number
  purchases: number
  outliers: number
  period_from: string | null
  period_to: string | null
}

export interface MatchRequestItem {
  id: string
  name: string
  description: string
  /** Для поиска в интернете: цена нужна за эту единицу. */
  unit?: string
  /** Раздел КП: прайсы того же раздела чуть надёжнее. */
  section?: string
}

/** Состояние поиска цен в интернете: настроен ли, чем ищем (claude | suppliers | fake), сколько в кэше. */
export interface InternetSearchInfo {
  configured: boolean
  provider: string
  model: string
  cached: number
  ttl_days: number
}

export type SupplierKind = 'site' | 'pricelist'
export type SupplierStatus = 'idle' | 'running' | 'done' | 'error'

/** Поставщик, чьи цены собираем: сайт (обход каталога) и/или прайс-лист xlsx. */
export interface Supplier {
  id: string
  name: string
  site: string
  kind: SupplierKind
  /** Что нашли: адрес фида/карты сайта или имя файла прайса. */
  source: string
  offers: number
  collected_at: string
  status: SupplierStatus
  progress: string
  error: string
  max_pages: number
  /** Найден автопоиском, а не заведён оператором. */
  discovered: boolean
  /** По какому запросу нашёлся. */
  query: string
  /** Каталог обходили целиком (а не только страницы из поиска). */
  crawled: boolean
  /** Разделы КП, которые закрывает поставщик. */
  sections: string[]
}

export interface SupplierOffer {
  supplier_id: string
  supplier: string
  name: string
  price: number
  url: string
  sku: string
  collected_at: string
  /** Раздел прайса, если загружали прайс по разделу. */
  section: string
}

export interface IndexationPair {
  years: string
  rate: number
  samples: number
}

export interface IndexationGroup {
  group: string
  /** % в год по последним годам; null — данных мало. */
  rate: number | null
  samples: number
  pairs: IndexationPair[]
}

/** Рост цен по истории закупок: по группам и в целом. */
export interface HistoryIndexation {
  overall: IndexationGroup | null
  groups: IndexationGroup[]
  computed_at: string
}

export type IndexationSource = 'history' | 'supplier' | 'official' | 'manual'

/** Ставка индексации раздела, выбранная оператором; раздел «» — для разделов без своей ставки. */
export interface IndexationRate {
  section: string
  rate: number
  source: IndexationSource
  note: string
  updated_at: string
}

export interface IndexationInfo {
  /** null — история закупок не загружена. */
  history: HistoryIndexation | null
  rates: IndexationRate[]
}

/** Индексация в выгрузке и в расчёте КП: дата поставки и ставки по разделам (ключ «» — по умолчанию). */
export interface Indexation {
  date: string
  rates: Record<string, number>
  apply_to_kp: boolean
}

export interface SupplierIndexInfo {
  suppliers: Supplier[]
  offers: number
  updated_at: string
  /** Сколько страниц обходить у сайтов, найденных автопоиском; 0 — не обходить. */
  autocrawl_pages: number
  /** Искать в интернете, пока по позиции меньше стольких разных магазинов. */
  min_shops: number
  queued: number
  /** Чем ищем в интернете; пусто — автопоиск выключен. */
  search_engine: string
}

export interface Health {
  status: string
  engine: { available: boolean; ocr: string | null }
}

interface ApiResponse<T> {
  success: boolean
  data: T
  message?: string
  errors: string[]
}

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
    if (typeof body?.title === 'string') return body.title
  } catch {
    // тело не JSON — вернём статус
  }
  return `Ошибка ${response.status}`
}

async function readData<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as ApiResponse<T>
  return body.data
}

// Под /api/specifications/, а не /api/health: на общем домене (testdesign…/spec/) край отдаёт
// приложению только этот префикс, а /api/health там отвечает другой сервис.
export function getHealth(): Promise<Health> {
  return fetch('/api/specifications/health').then((r) => readData<Health>(r))
}

export function parsePdf(file: File): Promise<ParsedDocument> {
  const form = new FormData()
  form.append('file', file)
  return fetch('/api/specifications/parse', { method: 'POST', body: form }).then((r) => readData<ParsedDocument>(r))
}

export function getPriceList(): Promise<PriceListInfo | null> {
  // Пока прайс не загружен, api отвечает конвертом без data — это «нет прайса», а не ошибка.
  return fetch('/api/specifications/pricelist').then((r) => readData<PriceListInfo | null | undefined>(r).then((d) => d ?? null))
}

export function uploadPriceList(file: File): Promise<PriceListInfo> {
  const form = new FormData()
  form.append('file', file)
  return fetch('/api/specifications/pricelist', { method: 'POST', body: form }).then((r) => readData<PriceListInfo>(r))
}

export function matchHistory(items: MatchRequestItem[]): Promise<Record<string, HistoryPrice>> {
  return fetch('/api/specifications/pricelist/match', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  }).then((r) => readData<{ matches: Record<string, HistoryPrice> }>(r).then((d) => d.matches))
}

export function getInternetSearch(): Promise<InternetSearchInfo> {
  return fetch('/api/specifications/internet').then((r) => readData<InternetSearchInfo>(r))
}

/** Поиск цен пачкой (до 50 позиций); refresh — искать заново, не глядя на кэш. Ждать приходится долго. */
export function lookupInternet(items: MatchRequestItem[], refresh = false): Promise<Record<string, InternetLookup>> {
  return fetch('/api/specifications/internet/lookup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items, refresh }),
  }).then((r) => readData<{ lookups: Record<string, InternetLookup> }>(r).then((d) => d.lookups))
}

const SUPPLIERS = '/api/specifications/suppliers'

export function getSuppliers(): Promise<SupplierIndexInfo> {
  return fetch(SUPPLIERS).then((r) => readData<SupplierIndexInfo>(r))
}

export function addSupplier(body: { name: string; site: string; max_pages?: number; sections?: string[] }): Promise<Supplier> {
  return fetch(SUPPLIERS, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then((r) => readData<Supplier>(r))
}

export function updateSupplier(id: string, body: { name?: string; sections?: string[]; max_pages?: number }): Promise<Supplier> {
  return fetch(`${SUPPLIERS}/${encodeURIComponent(id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then((r) =>
    readData<Supplier>(r),
  )
}

export function getIndexation(): Promise<IndexationInfo> {
  return fetch('/api/specifications/indexation').then((r) => readData<IndexationInfo>(r))
}

/** Справочник ставок заменяется целиком. */
export function setIndexationRates(rates: Omit<IndexationRate, 'updated_at'>[]): Promise<IndexationInfo> {
  return fetch('/api/specifications/indexation', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rates }) }).then((r) =>
    readData<IndexationInfo>(r),
  )
}

export async function removeSupplier(id: string): Promise<void> {
  const response = await fetch(`${SUPPLIERS}/${encodeURIComponent(id)}`, { method: 'DELETE' })
  if (!response.ok) throw new Error(await readError(response))
}

export function crawlSupplier(id: string): Promise<Supplier> {
  return fetch(`${SUPPLIERS}/${encodeURIComponent(id)}/crawl`, { method: 'POST' }).then((r) => readData<Supplier>(r))
}

export function stopSupplier(id: string): Promise<Supplier> {
  return fetch(`${SUPPLIERS}/${encodeURIComponent(id)}/stop`, { method: 'POST' }).then((r) => readData<Supplier>(r))
}

export function uploadSupplierPriceList(id: string, file: File, section = ''): Promise<Supplier> {
  const form = new FormData()
  form.append('file', file)
  if (section.trim()) form.append('section', section.trim())
  return fetch(`${SUPPLIERS}/${encodeURIComponent(id)}/pricelist`, { method: 'POST', body: form }).then((r) => readData<Supplier>(r))
}

export function updateSupplierSettings(body: { autocrawl_pages: number; min_shops: number }): Promise<SupplierIndexInfo> {
  return fetch(`${SUPPLIERS}/settings`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then((r) =>
    readData<SupplierIndexInfo>(r),
  )
}

export function sampleSupplierOffers(id: string): Promise<SupplierOffer[]> {
  return fetch(`${SUPPLIERS}/${encodeURIComponent(id)}/sample`).then((r) => readData<{ offers: SupplierOffer[] }>(r).then((d) => d.offers))
}

export async function exportExcel(doc: ParsedDocument): Promise<{ blob: Blob; fileName: string }> {
  const r = await fetch('/api/specifications/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(doc),
  })
  if (!r.ok) throw new Error(await readError(r))
  const disposition = r.headers.get('Content-Disposition') ?? ''
  const match = /filename\*=UTF-8''([^;]+)/.exec(disposition)
  const fileName = match ? decodeURIComponent(match[1]) : 'спецификация.xlsx'
  return { blob: await r.blob(), fileName }
}
