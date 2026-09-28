import { Button, Group, NumberInput, Paper, Select, Stack, Switch, Table, Text, TextInput, Tooltip } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useEffect, useMemo, useState } from 'react'

import { getIndexation, setIndexationRates, type HistoryIndexation, type IndexationGroup, type IndexationSource } from '../api'
import { indexedPrice, yearsBetween } from '../kp'
import { useWorkspace } from '../store'
import { formatMoney } from './format'

const SOURCE_OPTIONS: { value: IndexationSource; label: string }[] = [
  { value: 'history', label: 'история закупок' },
  { value: 'supplier', label: 'ответ поставщика' },
  { value: 'official', label: 'официальный индекс' },
  { value: 'manual', label: 'вручную' },
]
const OTHER = '' // ставка по умолчанию — для разделов без своей

interface RateRow {
  section: string
  rate: number | string
  source: IndexationSource
  note: string
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

function formatRate(rate: number): string {
  return `${rate > 0 ? '+' : ''}${rate.toLocaleString('ru-RU', { maximumFractionDigits: 1 })} %`
}

/** Группа истории закупок, похожая на раздел КП: точное имя, иначе общее начало, иначе «все группы». */
function historyGroupFor(section: string, history: HistoryIndexation | null): IndexationGroup | null {
  if (!history) return null
  if (section === OTHER) return history.overall
  const key = section.trim().toLowerCase()
  const exact = history.groups.find((g) => g.group.trim().toLowerCase() === key)
  if (exact) return exact
  const prefix = history.groups.find((g) => {
    const name = g.group.trim().toLowerCase()
    return name.length >= 6 && key.length >= 6 && (key.startsWith(name) || name.startsWith(key))
  })
  return prefix ?? history.overall
}

export function IndexationPanel() {
  const documents = useWorkspace((s) => s.documents)
  const indexation = useWorkspace((s) => s.indexation)
  const setIndexation = useWorkspace((s) => s.setIndexation)

  const [history, setHistory] = useState<HistoryIndexation | null>(null)
  const [serverRates, setServerRates] = useState<Record<string, RateRow> | null>(null)
  const [rows, setRows] = useState<RateRow[]>([])
  const [saving, setSaving] = useState(false)

  const active = useMemo(() => documents.flatMap((d) => d.doc.summary).filter((r) => !r.excluded), [documents])
  const sections = useMemo(() => Array.from(new Set(active.map((r) => r.section.trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'ru')), [active])
  const sectionsKey = sections.join('|')

  useEffect(() => {
    getIndexation()
      .then((info) => {
        setHistory(info.history)
        const known: Record<string, RateRow> = {}
        for (const r of info.rates) known[r.section] = { section: r.section, rate: r.rate, source: r.source, note: r.note }
        setServerRates(known)
        setIndexation({ rates: Object.fromEntries(info.rates.map((r) => [r.section, r.rate])) })
      })
      .catch((e) => notifications.show({ color: 'red', title: 'Индексация', message: message(e) }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Строки таблицы: разделы объекта плюс «прочие»; сохранённые ставки — как есть, остальные — из истории.
  useEffect(() => {
    if (serverRates === null) return
    const wanted = [...sections, OTHER]
    setRows((current) => {
      const byKey = new Map(current.map((r) => [r.section, r]))
      return wanted.map((section) => {
        const existing = byKey.get(section) ?? serverRates[section]
        if (existing) return existing
        const group = historyGroupFor(section, history)
        return group && group.rate !== null
          ? { section, rate: group.rate, source: 'history', note: `по истории: ${group.group}, ${group.samples} сравн.` }
          : { section, rate: '', source: 'manual', note: '' }
      })
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverRates, sectionsKey, history])

  const draftRates = useMemo(() => Object.fromEntries(rows.filter((r) => typeof r.rate === 'number').map((r) => [r.section, r.rate as number])), [rows])
  const years = indexation.date ? yearsBetween(new Date().toISOString().slice(0, 10), indexation.date) : 0
  const totals = useMemo(() => {
    let today = 0
    let dated = 0
    for (const row of active) {
      if (row.price === null || row.qty === null) continue
      today += row.price * row.qty
      dated += indexedPrice(row.price, row.section, { date: indexation.date, rates: draftRates, apply_to_kp: false }) * row.qty
    }
    return { today, dated }
  }, [active, indexation.date, draftRates])

  function patch(section: string, change: Partial<RateRow>) {
    setRows((current) => current.map((r) => (r.section === section ? { ...r, ...change } : r)))
  }

  function fromHistory() {
    setRows((current) =>
      current.map((r) => {
        const group = historyGroupFor(r.section, history)
        return group && group.rate !== null ? { ...r, rate: group.rate, source: 'history', note: `по истории: ${group.group}, ${group.samples} сравн.` } : r
      }),
    )
  }

  async function save() {
    setSaving(true)
    try {
      const payload = rows.filter((r) => typeof r.rate === 'number').map((r) => ({ section: r.section, rate: r.rate as number, source: r.source, note: r.note }))
      const info = await setIndexationRates(payload)
      const known: Record<string, RateRow> = {}
      for (const r of info.rates) known[r.section] = { section: r.section, rate: r.rate, source: r.source, note: r.note }
      setServerRates(known)
      setRows((current) => current.map((r) => known[r.section] ?? r))
      setIndexation({ rates: Object.fromEntries(info.rates.map((r) => [r.section, r.rate])) })
      notifications.show({ color: 'green', message: `Ставки сохранены: ${info.rates.length}` })
    } catch (e) {
      notifications.show({ color: 'red', title: 'Не удалось сохранить ставки', message: message(e) })
    } finally {
      setSaving(false)
    }
  }

  const dirty = rows.some((r) => {
    const saved = serverRates?.[r.section]
    return typeof r.rate === 'number' && (!saved || saved.rate !== r.rate || saved.source !== r.source || saved.note !== r.note)
  })

  return (
    <Paper withBorder p="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-end" wrap="wrap">
          <div>
            <Text fw={700}>Индексация к дате поставки</Text>
            <Text size="xs" c="dimmed" maw={640}>
              Ставка в процентах за год по разделу: из ответа поставщика, официального индекса или своей истории закупок (изменение цен одних и
              тех же позиций год к году, медиана по разделу). Цена на дату = цена × (1 + ставка)^(лет до даты). В выгрузке «Себестоимость» —
              графы «Индексация», «Цена на дату» и «Стоимость на дату», в КП — если включено ниже.
            </Text>
          </div>
          <Group align="flex-end">
            <TextInput type="date" label="Дата поставки" value={indexation.date} onChange={(e) => setIndexation({ date: e.currentTarget.value })} w={170} />
            <Switch
              label="Учитывать в КП"
              checked={indexation.apply_to_kp}
              disabled={!indexation.date}
              onChange={(e) => setIndexation({ apply_to_kp: e.currentTarget.checked })}
            />
          </Group>
        </Group>

        {history?.overall && history.overall.rate !== null && (
          <Text size="sm" c="dimmed">
            По истории закупок в целом: {formatRate(history.overall.rate)} в год ({history.overall.samples} сравнений
            {history.overall.pairs.length > 0 && `; по годам: ${history.overall.pairs.map((p) => `${p.years} ${formatRate(p.rate)}`).join(', ')}`})
          </Text>
        )}
        {history === null && serverRates !== null && (
          <Text size="sm" c="dimmed">
            История закупок не загружена — ставки по истории недоступны, задайте вручную или по ответам поставщиков.
          </Text>
        )}

        <Table withTableBorder withColumnBorders fz="sm" verticalSpacing={4}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Раздел</Table.Th>
              <Table.Th w={140}>Ставка, % в год</Table.Th>
              <Table.Th w={190}>Источник</Table.Th>
              <Table.Th w={220}>По истории</Table.Th>
              <Table.Th>Примечание</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((r) => {
              const group = historyGroupFor(r.section, history)
              return (
                <Table.Tr key={r.section || '__other'}>
                  <Table.Td>
                    <Text size="sm" fw={r.section ? 500 : 400} c={r.section ? undefined : 'dimmed'}>
                      {r.section || 'Прочие разделы (по умолчанию)'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <NumberInput size="xs" value={r.rate} onChange={(v) => patch(r.section, { rate: typeof v === 'number' ? v : '' })} min={-50} max={200} decimalScale={1} step={0.5} />
                  </Table.Td>
                  <Table.Td>
                    <Select size="xs" data={SOURCE_OPTIONS} value={r.source} onChange={(v) => patch(r.section, { source: (v as IndexationSource) ?? 'manual' })} allowDeselect={false} />
                  </Table.Td>
                  <Table.Td>
                    {group && group.rate !== null ? (
                      <Tooltip label={group.pairs.map((p) => `${p.years}: ${formatRate(p.rate)} (${p.samples})`).join('; ') || 'мало данных по годам'} multiline w={320}>
                        <Text size="xs" style={{ cursor: 'help' }}>
                          {formatRate(group.rate)} · {group.group} · {group.samples} сравн.
                        </Text>
                      </Tooltip>
                    ) : (
                      <Text size="xs" c="dimmed">
                        {history ? 'мало данных' : '—'}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <TextInput size="xs" value={r.note} onChange={(e) => patch(r.section, { note: e.currentTarget.value })} placeholder="откуда ставка, дата ответа поставщика" />
                  </Table.Td>
                </Table.Tr>
              )
            })}
          </Table.Tbody>
        </Table>

        <Group justify="space-between" wrap="wrap">
          <Group>
            <Button variant="light" size="xs" onClick={fromHistory} disabled={!history}>
              Взять из истории
            </Button>
            <Button size="xs" onClick={save} loading={saving} disabled={!dirty}>
              Сохранить ставки
            </Button>
          </Group>
          {indexation.date && (
            <Text size="sm">
              Себестоимость сегодня {formatMoney(totals.today)} ₽ → на {indexation.date}: <b>{formatMoney(totals.dated)} ₽</b> ({years.toFixed(2)} г.
              {totals.today > 0 && `, ${formatRate(((totals.dated - totals.today) / totals.today) * 100)}`})
            </Text>
          )}
        </Group>
      </Stack>
    </Paper>
  )
}
