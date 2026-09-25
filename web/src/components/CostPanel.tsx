import { Alert, Anchor, Badge, Button, FileButton, Group, Menu, Pagination, Paper, Progress, SegmentedControl, Stack, Table, Text, TextInput } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconChevronDown, IconDatabaseImport, IconFileDownload, IconRefresh, IconWorldSearch } from '@tabler/icons-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
  getInternetSearch,
  getPriceList,
  lookupInternet,
  matchHistory,
  uploadPriceList,
  type HistoryPrice,
  type InternetSearchInfo,
  type MatchKind,
  type PriceListInfo,
} from '../api'
import { useWorkspace, type HistoryChoice, type RowKey, type SummaryRow } from '../store'
import { useUi } from '../ui'
import { CostRowView } from './CostRow'
import { formatMoney } from './format'
import { TableScroller } from './TableScroller'

interface Props {
  onDownload: () => void
  downloading: boolean
}

type Mode = 'all' | 'unmatched' | 'nointernet' | 'noprice'
const PAGE_SIZE = 50
// Поиск в интернете — десятки секунд на позицию; пачки маленькие, чтобы прогресс был виден
// и обрыв связи не терял уже найденное.
const LOOKUP_BATCH = 8
const COST_COLUMNS: (number | null)[] = [44, 90, null, 90, 250, 140, 120, 120, 120, 130, 120]

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
  const applyInternet = useWorkspace((s) => s.applyInternet)
  const chooseInternetPrice = useWorkspace((s) => s.chooseInternetPrice)
  const chooseOffer = useWorkspace((s) => s.chooseOffer)
  const openSuppliers = useUi((s) => s.openSuppliers)

  const [priceList, setPriceList] = useState<PriceListInfo | null | undefined>(undefined)
  const [internet, setInternet] = useState<InternetSearchInfo | null | undefined>(undefined)
  const [uploading, setUploading] = useState(false)
  const [matching, setMatching] = useState(false)
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const cancelRef = useRef(false)
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
    getInternetSearch()
      .then(setInternet)
      .catch(() => setInternet(null))
  }, [])

  const rows = useMemo<FlatRow[]>(
    () => documents.flatMap((d) => d.doc.summary.map((row, index) => ({ key: { docId: d.id, index }, id: `${d.id}:${index}`, row }))).filter((r) => !r.row.excluded),
    [documents],
  )

  const stats = useMemo(() => {
    const kinds: Record<MatchKind | 'pending', number> = { exact: 0, fuzzy: 0, analog: 0, none: 0, pending: 0 }
    const net = { found: 0, notFound: 0, error: 0, pending: 0 }
    let sum = 0
    let priced = 0
    for (const { row } of rows) {
      kinds[row.history?.kind ?? 'pending'] += 1
      const status = row.internet?.status
      if (!status) net.pending += 1
      else if (status === 'found') net.found += 1
      else if (status === 'error') net.error += 1
      else net.notFound += 1
      if (row.price !== null && row.qty !== null) {
        sum += row.price * row.qty
        priced += 1
      }
    }
    return { kinds, net, sum, priced }
  }, [rows])

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase()
    return rows.filter(({ row }) => {
      if (mode === 'unmatched' && row.history && row.history.kind !== 'none' && row.history.kind !== 'analog') return false
      if (mode === 'nointernet' && row.internet?.status === 'found') return false
      if (mode === 'noprice' && row.price !== null) return false
      if (!q) return true
      return (
        row.pos.toLowerCase().includes(q) ||
        row.name.toLowerCase().includes(q) ||
        row.description.toLowerCase().includes(q) ||
        (row.history?.best?.name ?? '').toLowerCase().includes(q)
      )
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
      const merged: Record<string, HistoryPrice> = {}
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

  const missingInternet = rows.filter((r) => !r.row.internet || r.row.internet.status === 'error')

  async function searchInternet(scope: 'missing' | 'all') {
    const targets = scope === 'all' ? rows : missingInternet
    if (targets.length === 0) {
      notifications.show({ color: 'blue', message: 'Все позиции уже искали в интернете' })
      return
    }
    cancelRef.current = false
    setProgress({ done: 0, total: targets.length })
    let searches = 0
    let stopped = false
    try {
      for (let i = 0; i < targets.length; i += LOOKUP_BATCH) {
        if (cancelRef.current) {
          stopped = true
          break
        }
        const batch = targets.slice(i, i + LOOKUP_BATCH)
        const lookups = await lookupInternet(
          batch.map((r) => ({ id: r.id, name: r.row.name, description: r.row.description, unit: r.row.unit })),
          scope === 'all',
        )
        applyInternet(lookups)
        searches += Object.values(lookups).reduce((n, l) => n + (l.searches ?? 0), 0)
        setProgress({ done: Math.min(i + batch.length, targets.length), total: targets.length })
      }
      notifications.show({
        color: stopped ? 'yellow' : 'green',
        title: stopped ? 'Поиск остановлен' : 'Поиск в интернете завершён',
        message: `Поисковых запросов к модели: ${searches}`,
      })
    } catch (e) {
      notifications.show({ color: 'red', title: 'Поиск в интернете прервался', message: e instanceof Error ? e.message : String(e) })
    } finally {
      setProgress(null)
      getInternetSearch()
        .then(setInternet)
        .catch(() => undefined)
    }
  }

  const matchedKeys = rows.filter((r) => r.row.history?.best).map((r) => r.key)
  const internetKeys = rows.filter((r) => r.row.internet_price !== null && r.row.internet_price !== undefined).map((r) => r.key)
  const chooseAll = (which: HistoryChoice) => chooseHistoryPrice(matchedKeys, which)
  const searchReady = internet?.configured === true && rows.length > 0 && progress === null

  return (
    <Stack gap="md">
      <Paper withBorder p="md">
        <Group justify="space-between" align="flex-start" wrap="wrap" gap="lg">
          <div style={{ flex: 1, minWidth: 320 }}>
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
            <Text fw={700} mt="sm">
              Цена из интернета на дату
            </Text>
            {internet === undefined && (
              <Text size="sm" c="dimmed">
                проверяем…
              </Text>
            )}
            {internet === null && (
              <Text size="sm" c="dimmed">
                сервис недоступен
              </Text>
            )}
            {internet && !internet.configured && (
              <Text size="sm" c="dimmed">
                Не настроен. Бесплатный путь — каталоги и прайсы поставщиков (кнопка «Поставщики» вверху); платный — ключ ANTHROPIC_API_KEY на
                сервере ядра, тогда модель сама ищет предложения в интернете.
              </Text>
            )}
            {internet?.configured && internet.provider === 'suppliers' && (
              <Text size="sm" c="dimmed">
                {internet.model} ·{' '}
                <Anchor size="sm" onClick={openSuppliers}>
                  настроить поставщиков
                </Anchor>
              </Text>
            )}
            {internet?.configured && internet.provider !== 'suppliers' && (
              <Text size="sm" c="dimmed">
                модель {internet.model} · в кэше {internet.cached} позиций · найденное свежее {internet.ttl_days} дн. заново не ищется
              </Text>
            )}
            {progress && (
              <Group gap="sm" mt="xs" wrap="nowrap">
                <Progress value={(progress.done / progress.total) * 100} w={220} animated />
                <Text size="sm">
                  {progress.done} из {progress.total}
                </Text>
                <Button size="compact-xs" variant="subtle" color="red" onClick={() => (cancelRef.current = true)}>
                  Остановить
                </Button>
              </Group>
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
            <Menu shadow="md" width={320} transitionProps={{ duration: 0 }}>
              <Menu.Target>
                <Button
                  variant="light"
                  leftSection={<IconWorldSearch size={16} />}
                  rightSection={<IconChevronDown size={14} />}
                  loading={progress !== null}
                  disabled={!searchReady}
                >
                  {internet?.provider === 'suppliers' ? 'Найти цены у поставщиков' : 'Найти цены в интернете'}
                </Button>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Item onClick={() => searchInternet('missing')} disabled={missingInternet.length === 0}>
                  Только там, где ещё не искали ({missingInternet.length})
                </Menu.Item>
                <Menu.Item onClick={() => searchInternet('all')}>Все позиции заново ({rows.length})</Menu.Item>
              </Menu.Dropdown>
            </Menu>
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
            <Badge variant="light" color="blue">
              интернет: {stats.net.found}
            </Badge>
            {stats.net.error > 0 && (
              <Badge variant="light" color="red">
                ошибки поиска: {stats.net.error}
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
            <Button size="xs" variant="light" disabled={internetKeys.length === 0} onClick={() => chooseInternetPrice(internetKeys)}>
              интернет
            </Button>
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
          Три цены на позицию: интернет на дату, минимум и максимум по истории закупок. Щелчок по цене берёт её в базовую; базовую можно и
          вписать руками. Из базовой цены считается КП. Наведите на сопоставление или цену из интернета — увидите кандидатов, покупки и
          найденные предложения со ссылками; щелчок по предложению делает его ценой из интернета для позиции.
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
            { value: 'nointernet', label: 'Без цены из интернета' },
            { value: 'noprice', label: 'Без цены' },
          ]}
        />
        {pages > 1 && <Pagination total={pages} value={currentPage} onChange={setPage} size="sm" />}
        <Text size="sm" c="dimmed">
          {pages > 1 ? `строки ${(currentPage - 1) * PAGE_SIZE + 1}–${Math.min(currentPage * PAGE_SIZE, visible.length)} из ${visible.length}` : `Строк: ${visible.length}`}
        </Text>
      </Group>

      <TableScroller minWidth={1580}>
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
              <CostRowView
                key={r.id}
                number={(currentPage - 1) * PAGE_SIZE + i + 1}
                row={r.row}
                rowKey={r.key}
                onChange={updateRow}
                onChoose={chooseHistoryPrice}
                onChooseInternet={chooseInternetPrice}
                onOffer={chooseOffer}
              />
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
