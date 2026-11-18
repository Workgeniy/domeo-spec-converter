// Мост к браузерному расширению Domeo (цены с маркетплейсов). Расширение держит «почтовый ящик»
// в API на /ext/* (см. ExtensionBridgeController). Веб-интерфейс кладёт туда открытую спеку (чтобы в
// расширении был список «→ строку») и забирает найденные цены, раскладывая их в тот же слот строки,
// что и обычный поиск в интернете (готовый UI: показ цены, выбор предложения, «взять в базовую»).
//
// Работает только в десктоп-сборке, где API отдаёт и SPA, и /ext на одном origin. На общем стенде
// /ext недоступен — мост сам выключается (ping не пройдёт), веб работает как прежде.

import { useEffect, useState } from 'react'
import { notifications } from '@mantine/notifications'

import { readData } from './api'
import type { InternetLookup, InternetOffer } from './api'
import { rowKey, useWorkspace } from './store'

export interface BridgeFoundPrice {
  spec_item_id: string
  source: string
  name: string
  price: number
  old_price?: number | null
  article_id?: string | null
  url?: string | null
  seller?: string | null
  brand?: string | null
  rating?: number | null
  reviews?: number | null
  vat_rate?: number | null
  vat_refund?: boolean
}

export interface BridgeSpecLine {
  id: string
  name: string
  qty: number
}

const SHOP: Record<string, string> = {
  wildberries: 'Wildberries',
  ozon: 'Ozon',
  yandexmarket: 'Яндекс.Маркет',
  megamarket: 'Мегамаркет',
  vseinstrumenti: 'ВсеИнструменти',
  lemana: 'Лемана ПРО',
  dns: 'DNS',
  citilink: 'Ситилинк',
  petrovich: 'Петрович',
}

export const shopName = (source: string): string => SHOP[source] ?? source

/** Доступен ли мост (десктоп-сборка). Тихо false, если /ext недоступен (общий стенд, нет приложения). */
export async function pingBridge(): Promise<boolean> {
  try {
    const r = await fetch('/ext/ping', { signal: AbortSignal.timeout(2500) })
    if (!r.ok) return false
    const body = (await r.json()) as { data?: { app?: string } }
    return body?.data?.app === 'domeo'
  } catch {
    return false
  }
}

/** Положить открытую спеку в мост — для выпадающего списка «→ строку» в расширении. */
export async function pushSpec(lines: BridgeSpecLine[]): Promise<void> {
  try {
    await fetch('/ext/spec/current', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(lines),
    })
  } catch {
    // мост мог пропасть — не мешаем работе
  }
}

/** Забрать накопленные расширением цены (очередь на сервере очищается). */
export async function drainPrices(): Promise<BridgeFoundPrice[]> {
  try {
    const r = await fetch('/ext/prices', { signal: AbortSignal.timeout(2500) })
    return await readData<BridgeFoundPrice[]>(r)
  } catch {
    return []
  }
}

/** Рекомендуемая цена = нижняя медиана предложений: устойчива и к дешёвым аксессуарам (пример: «фиксаторы
 *  для ковра» за 212 ₽ в выдаче «ковёр»), и к задранным ценам; и это всегда реальная цена из списка. */
function medianPrice(offers: InternetOffer[]): number | null {
  const ps = offers.map((o) => o.price).filter((p) => p > 0).sort((a, b) => a - b)
  if (!ps.length) return null
  return ps[Math.floor((ps.length - 1) / 2)]
}

/** Сгруппировать цены по строке спеки и собрать для каждой «результат поиска в интернете»,
 *  чтобы цена легла в готовый слот строки (предложения, рекомендуемая цена, «взять в базовую»). */
export function pricesToLookups(prices: BridgeFoundPrice[]): Record<string, InternetLookup> {
  const byRow = new Map<string, BridgeFoundPrice[]>()
  for (const p of prices) {
    if (!p.spec_item_id) continue
    const list = byRow.get(p.spec_item_id) ?? []
    list.push(p)
    byRow.set(p.spec_item_id, list)
  }
  const today = new Date().toISOString().slice(0, 10)
  const out: Record<string, InternetLookup> = {}
  for (const [id, list] of byRow) {
    const offers: InternetOffer[] = list.map((p) => ({
      title: p.name,
      url: p.url ?? '',
      shop: shopName(p.source),
      price: p.price,
      analog: false,
      note: p.old_price ? `было ${p.old_price} ₽` : '',
      vat_rate: p.vat_rate ?? null,
      vat_refund: !!p.vat_refund,
    }))
    const price = medianPrice(offers) // рекомендуемая = медиана (устойчива к аксессуарам/выбросам)
    out[id] = {
      status: 'found',
      query: list[0].name,
      looked_up_at: today,
      offers,
      price,
      comment: 'из расширения (маркетплейсы)',
      provider: 'extension',
      searches: 0,
      params: [],
      image: '',
    }
  }
  return out
}

/** Накопить предложения по строке: прежние (из расширения) + новые, без дублей, минимум — рекомендуемая.
 *  Так параллельные проходы по разным маркетплейсам (WB/DNS/Ситилинк по вкладке) складывают цены в одну
 *  строку, а не затирают друг друга. С неэкстеншн-результатом (старый индекс) не мешаем — заменяем. */
function mergeWithExisting(fresh: Record<string, InternetLookup>): Record<string, InternetLookup> {
  const docs = useWorkspace.getState().documents
  const findInternet = (id: string): InternetLookup | undefined => {
    const sep = id.lastIndexOf(':')
    if (sep < 0) return undefined
    const docId = id.slice(0, sep)
    const idx = Number(id.slice(sep + 1))
    const d = docs.find((x) => x.id === docId)
    return d?.doc.summary[idx]?.internet ?? undefined
  }
  const out: Record<string, InternetLookup> = {}
  for (const [id, lk] of Object.entries(fresh)) {
    const ex = findInternet(id)
    const fromExt = !!ex && ex.status === 'found' && (ex.provider === 'extension' || (ex.comment ?? '').includes('расширени'))
    if (fromExt && ex!.offers.length) {
      const seen = new Set<string>()
      const all: InternetOffer[] = []
      for (const o of [...ex!.offers, ...lk.offers]) {
        const k = `${o.shop}|${o.url || o.title}|${o.price}`
        if (seen.has(k)) continue
        seen.add(k)
        all.push(o)
      }
      const price = medianPrice(all)
      out[id] = { ...lk, offers: all, price }
    } else {
      out[id] = lk
    }
  }
  return out
}

/** Текущие строки открытой спеки для моста: id = ключ строки (docId:index), имя для списка, кол-во. */
function currentSpecLines(): BridgeSpecLine[] {
  const lines: BridgeSpecLine[] = []
  for (const d of useWorkspace.getState().documents) {
    d.doc.summary.forEach((row, i) => {
      if (row.excluded) return
      const name = [row.pos, row.name].filter(Boolean).join(' ').trim() || row.name || '—'
      lines.push({ id: rowKey({ docId: d.id, index: i }), name, qty: row.qty ?? 0 })
    })
  }
  return lines
}

/** Связь веб-интерфейса с расширением: отдаёт спеку в мост и подхватывает присланные цены.
 *  Монтируется один раз (в App). На общем стенде/без приложения тихо ничего не делает. */
export function useExtensionBridge(): void {
  const [available, setAvailable] = useState(false)

  // 1) доступен ли мост (десктоп)
  useEffect(() => {
    let alive = true
    void pingBridge().then((ok) => {
      if (alive) setAvailable(ok)
    })
    return () => {
      alive = false
    }
  }, [])

  // 2) класть открытую спеку в мост при её изменениях (подписка на store, без ререндеров App)
  useEffect(() => {
    if (!available) return
    let timer: ReturnType<typeof setTimeout> | undefined
    const schedule = () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => void pushSpec(currentSpecLines()), 400)
    }
    schedule() // первичная отправка
    const unsub = useWorkspace.subscribe((s, prev) => {
      if (s.documents !== prev.documents) schedule()
    })
    return () => {
      if (timer) clearTimeout(timer)
      unsub()
    }
  }, [available])

  // 3) опрашивать мост на присланные цены и раскладывать их по строкам
  useEffect(() => {
    if (!available) return
    let alive = true
    const tick = async () => {
      const prices = await drainPrices()
      if (!alive || prices.length === 0) return
      const lookups = mergeWithExisting(pricesToLookups(prices))
      useWorkspace.getState().applyInternet(lookups)
      notifications.show({
        color: 'teal',
        title: 'Цены из расширения',
        message: `Добавлено с маркетплейсов: ${prices.length} на ${Object.keys(lookups).length} поз.`,
      })
    }
    const id = setInterval(() => void tick(), 4000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [available])
}
