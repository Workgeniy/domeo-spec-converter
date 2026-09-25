import { Alert, Badge, Button, FileButton, Group, Pagination, Paper, SegmentedControl, Stack, Table, Text, TextInput } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconDatabaseImport, IconFileDownload, IconRefresh } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'

import { getPriceList, matchHistory, uploadPriceList, type MatchKind, type PriceListInfo } from '../api'
import { useWorkspace, type HistoryChoice, type RowKey, type SummaryRow } from '../store'
import { CostRowView } from './CostRow'
import { formatMoney } from './format'
import { TableScroller } from './TableScroller'

interface Props {
  onDownload: () => void
  downloading: boolean
}

type Mode = 'all' | 'unmatched' | 'noprice'
const PAGE_SIZE = 50
const COST_COLUMNS: (number | null)[] = [44, 90, null, 90, 260, 110, 120, 120, 120, 130, 120]

interface FlatRow {
  key: RowKey
  id: string
  row: SummaryRow
}

export function CostPanel({ onDownload, downloading }: Props) {
  const documents = useWorkspace((s) => s.documents)
  const updateRow = useWorkspace((s) => s.updateRow)
  const applyMatches = useWorkspace((s) => s.applyMatches)
  const chooseHistoryPrice = useWorkspace((s) => s.chooseHistoryPrice)

  const [priceList, setPriceList] = useState<PriceListInfo | null | undefined>(undefined)
  const [uploading, setUploading] = useState(false)
  const [matching, setMatching] = useState(false)
  const [filter, setFilter] = useState('')
  const [mode, setMode] = useState<Mode>('all')
  const [page, setPage] = useState(1)

  useEffect(() => {
    getPriceList()
      .then(setPriceList)
      .catch((e) => {
        setPriceList(null)
        notifications.show({ color: 'red', title: 'Прайс закупки', message: e instanceof Error ? e.message : String(e) })
      })
  }, [])

  const rows = useMemo<FlatRow[]>(
    () => documents.flatMap((d) => d.doc.summary.map((row, index) => ({ key: { docId: d.id, index }, id: `${d.id}:${index}`, row }))).filter((r) => !r.row.excluded),
    [documents],
  )

  const stats = useMemo(() => {
    const kinds: Record<MatchKind | 'pending', number> = { exact: 0, fuzzy: 0, analog: 0, none: 0, pending: 0 }
    let sum = 0
    let priced = 0
    for (const { row } of rows) {
      kinds[row.history?.kind ?? 'pending'] += 1
      if (row.price !== null && row.qty !== null) {
        sum += row.price * row.qty
        priced += 1
      }
    }
    return { kinds, sum, priced }
  }, [rows])

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase()
    return rows.filter(({ row }) => {
      if (mode === 'unmatched' && row.history && row.history.kind !== 'none' && row.history.kind !== 'analog') return false
      if (mode === 'noprice' && row.price !== null) return false
      if (!q) return true
      return row.pos.toLowerCase().includes(q) || row.name.toLowerCase().includes(q) || row.description.toLowerCase().includes(q) || (row.history?.best?.name ?? '').toLowerCase().includes(q)
    })
  }, [rows, filter, mode])

  const pages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE))
  useEffect(() => setPage(1), [filter, mode])
  const currentPage = Math.min(page, pages)
  const pageRows = visible.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

  async function upload(file: File | null) {
    if (!file) return
    setUploading(true)
    try {
      setPriceList(await uploadPriceList(file))
      notifications.show({ color: 'green', title: 'Прайс закупки собран', message: file.name })
    } catch (e) {
      notifications.show({ color: 'red', title: 'Не удалось загрузить выгрузку', message: e instanceof Error ? e.message : String(e) })
    } finally {
      setUploading(false)
    }
  }

  async function matchAll() {
    setMatching(true)
    try {
      const items = rows.map((r) => ({ id: r.id, name: r.row.name, description: r.row.description }))
      const merged: Record<string, import('../api').HistoryPrice> = {}
      // Порциями, чтобы запрос не разрастался на больших объектах.
      for (let i = 0; i < items.length; i += 500) {
        Object.assign(merged, await matchHistory(items.slice(i, i + 500)))
      }
      applyMatches(merged)
    } catch (e) {
      notifications.show({ color: 'red', title: 'Сопоставление не удалось', message: e instanceof Error ? e.message : String(e) })
    } finally {
      setMatching(false)
    }
  }

  const matchedKeys = rows.filter((r) => r.row.history?.best).map((r) => r.key)
  const chooseAll = (which: HistoryChoice) => chooseHistoryPrice(matchedKeys, which)

  return (
    <Stack gap="md">
      <Paper withBorder p="md">
        <Group justify="space-between" align="flex-start" wrap="wrap" gap="lg">
          <div>
            <Text fw={700}>Прайс закупки (история 1С)</Text>
            {priceList === undefined && (
              <Text size="sm" c="dimmed">
                проверяем…
              </Text>
            )}
            {priceList === null && (
              <Text size="sm" c="dimmed">
                Ещё не загружен. Нужна выгрузка «Заказы поставщикам» из 1С в xlsx: номенклатура, описание, группа, заказ, номенклатура
                партнёра, количество, сумма.
              </Text>
            )}
            {priceList && (
              <Text size="sm" c="dimmed">
                {priceList.source} · позиций {priceList.entries} · покупок {priceList.purchases} · период {priceList.period_from ?? '?'} —{' '}
                {priceList.period_to ?? '?'} · собран {priceList.built_at}
              </Text>
            )}
          </div>
          <Group>
            <FileButton onChange={upload} accept=".xlsx,.xlsm">
              {(props) => (
                <Button {...props} variant="default" leftSection={<IconDatabaseImport size={16} />} loading={uploading}>
                  {priceList ? 'Заменить выгрузку 1С' : 'Загрузить выгрузку 1С'}
                </Button>
              )}
            </FileButton>
            <Button leftSection={<IconRefresh size={16} />} loading={matching} disabled={!priceList || rows.length === 0} onClick={matchAll}>
              Сопоставить с историей
            </Button>
          </Group>
        </Group>
      </Paper>

      <Paper withBorder p="md">
        <Group justify="space-between" align="center" wrap="wrap" gap="lg">
          <Group gap="xs" wrap="wrap">
            <Badge variant="light" color="green">
              точно: {stats.kinds.exact}
            </Badge>
            <Badge variant="light" color="teal">
              похоже: {stats.kinds.fuzzy}
            </Badge>
            <Badge variant="light" color="orange">
              аналог: {stats.kinds.analog}
            </Badge>
            <Badge variant="light" color="gray">
              не найдено: {stats.kinds.none}
            </Badge>
            {stats.kinds.pending > 0 && (
              <Badge variant="outline" color="gray">
                не сопоставлено: {stats.kinds.pending}
              </Badge>
            )}
            <Badge variant="outline">
              с ценой: {stats.priced} из {rows.length}
            </Badge>
            <Badge variant="filled" color={stats.sum > 0 ? 'blue' : 'gray'}>
              себестоимость: {formatMoney(stats.sum)} ₽
            </Badge>
          </Group>
          <Group gap="xs" wrap="wrap">
            <Text size="sm" c="dimmed">
              Взять везде:
            </Text>
            <Button size="xs" variant="light" disabled={matchedKeys.length === 0} onClick={() => chooseAll('min')}>
              минимум
            </Button>
            <Button size="xs" variant="light" disabled={matchedKeys.length === 0} onClick={() => chooseAll('median')}>
              медиану
            </Button>
            <Button size="xs" variant="light" disabled={matchedKeys.length === 0} onClick={() => chooseAll('max')}>
              максимум
            </Button>
            <Button size="xs" variant="light" disabled={matchedKeys.length === 0} onClick={() => chooseAll('last')}>
              последнюю
            </Button>
            <Button leftSection={<IconFileDownload size={16} />} loading={downloading} disabled={rows.length === 0} onClick={onDownload}>
              Скачать себестоимость (Excel)
            </Button>
          </Group>
        </Group>
        <Text size="xs" c="dimmed" mt="sm">
          Три цены на позицию: интернет на дату (следующий шаг), минимум и максимум по истории закупок. Щелчок по цене берёт её в базовую;
          базовую можно и вписать руками. Из базовой цены считается КП. Наведите на сопоставление — увидите кандидатов и последние покупки.
        </Text>
      </Paper>

      {stats.kinds.analog > 0 && (
        <Alert color="orange" variant="light">
          У {stats.kinds.analog} позиций найден только аналог по словам — проверьте, тот ли это товар, прежде чем брать его цену.
        </Alert>
      )}

      <Group gap="sm" align="center" wrap="wrap">
        <TextInput placeholder="Поиск по позиции, описанию, найденному в истории" value={filter} onChange={(e) => setFilter(e.currentTarget.value)} w={360} size="sm" />
        <SegmentedControl
          size="xs"
          value={mode}
          onChange={(v) => setMode(v as Mode)}
          data={[
            { value: 'all', label: `Все (${rows.length})` },
            { value: 'unmatched', label: 'Аналог / не найдено' },
            { value: 'noprice', label: 'Без цены' },
          ]}
        />
        {pages > 1 && <Pagination total={pages} value={currentPage} onChange={setPage} size="sm" />}
        <Text size="sm" c="dimmed">
          {pages > 1 ? `строки ${(currentPage - 1) * PAGE_SIZE + 1}–${Math.min(currentPage * PAGE_SIZE, visible.length)} из ${visible.length}` : `Строк: ${visible.length}`}
        </Text>
      </Group>

      <TableScroller minWidth={1560}>
        <Table highlightOnHover withTableBorder withColumnBorders fz="sm" layout="fixed" verticalSpacing={4}>
          <colgroup>
            {COST_COLUMNS.map((w, i) => (
              <col key={i} style={w ? { width: w } : undefined} />
            ))}
          </colgroup>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>№</Table.Th>
              <Table.Th>№ поз.</Table.Th>
              <Table.Th>Позиция</Table.Th>
              <Table.Th>Кол-во</Table.Th>
              <Table.Th>Сопоставление с историей</Table.Th>
              <Table.Th>Интернет на дату</Table.Th>
              <Table.Th>Мин. по истории</Table.Th>
              <Table.Th>Макс. по истории</Table.Th>
              <Table.Th>Последняя закупка</Table.Th>
              <Table.Th>Выбранная цена, с НДС</Table.Th>
              <Table.Th>Стоимость</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {pageRows.map((r, i) => (
              <CostRowView key={r.id} number={(currentPage - 1) * PAGE_SIZE + i + 1} row={r.row} rowKey={r.key} onChange={updateRow} onChoose={chooseHistoryPrice} />
            ))}
            {pageRows.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={11}>
                  <Text size="sm" c="dimmed" ta="center" py="md">
                    Нет строк под этот фильтр
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </TableScroller>
    </Stack>
  )
}
