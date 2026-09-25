import { ActionIcon, Anchor, Badge, Button, FileButton, Group, NumberInput, Paper, Popover, ScrollArea, Stack, Table, Text, TextInput, Tooltip } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconEye, IconFileSpreadsheet, IconPlayerStop, IconPlus, IconRefresh, IconTrash } from '@tabler/icons-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { addSupplier, crawlSupplier, getSuppliers, removeSupplier, sampleSupplierOffers, stopSupplier, uploadSupplierPriceList, type Supplier, type SupplierIndexInfo, type SupplierOffer } from '../api'
import { formatMoney } from './format'

const POLL_MS = 3000

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

function StatusBadge({ supplier }: { supplier: Supplier }) {
  switch (supplier.status) {
    case 'running':
      return (
        <Badge color="blue" variant="light">
          собираем · {supplier.progress || '…'}
        </Badge>
      )
    case 'done':
      return (
        <Badge color="green" variant="light">
          собрано
        </Badge>
      )
    case 'error':
      return (
        <Tooltip label={supplier.error} multiline w={340}>
          <Badge color="red" variant="light" style={{ cursor: 'help' }}>
            {supplier.offers > 0 ? 'ошибка, есть старые цены' : 'не удалось'}
          </Badge>
        </Tooltip>
      )
    default:
      return (
        <Badge color="gray" variant="outline">
          ещё не собирали
        </Badge>
      )
  }
}

function SampleButton({ supplier }: { supplier: Supplier }) {
  const [opened, setOpened] = useState(false)
  const [offers, setOffers] = useState<SupplierOffer[] | null>(null)

  async function open() {
    setOpened((v) => !v)
    if (offers === null) {
      try {
        setOffers(await sampleSupplierOffers(supplier.id))
      } catch (e) {
        notifications.show({ color: 'red', title: 'Не удалось получить примеры', message: message(e) })
      }
    }
  }

  return (
    <Popover opened={opened} onChange={setOpened} width={620} shadow="md" withArrow transitionProps={{ duration: 0 }}>
      <Popover.Target>
        <Tooltip label="Примеры собранных позиций">
          <ActionIcon variant="subtle" onClick={open} disabled={supplier.offers === 0} aria-label="примеры">
            <IconEye size={16} />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown>
        <ScrollArea.Autosize mah={360}>
          <Text size="xs" fw={600} mb={6}>
            {supplier.name}: примеры из {supplier.offers} позиций
          </Text>
          {(offers ?? []).map((o, i) => (
            <Text key={i} size="xs" lineClamp={2}>
              {formatMoney(o.price)} — {o.name}
              {o.sku && (
                <Text span c="dimmed">
                  {' '}
                  · арт. {o.sku}
                </Text>
              )}
              {o.url && (
                <>
                  {' · '}
                  <Anchor href={o.url} target="_blank" rel="noopener noreferrer" size="xs">
                    открыть
                  </Anchor>
                </>
              )}
            </Text>
          ))}
          {offers === null && (
            <Text size="xs" c="dimmed">
              загружаем…
            </Text>
          )}
        </ScrollArea.Autosize>
      </Popover.Dropdown>
    </Popover>
  )
}

export function SuppliersPanel() {
  const [info, setInfo] = useState<SupplierIndexInfo | null>(null)
  const [name, setName] = useState('')
  const [site, setSite] = useState('')
  const [maxPages, setMaxPages] = useState<number | string>(3000)
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  const refresh = useCallback(async () => {
    try {
      setInfo(await getSuppliers())
    } catch (e) {
      notifications.show({ color: 'red', title: 'Поставщики', message: message(e) })
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Пока идёт хотя бы один обход — опрашиваем состояние.
  useEffect(() => {
    const running = info?.suppliers.some((s) => s.status === 'running') ?? false
    if (running && timer.current === null) {
      timer.current = window.setInterval(() => void refresh(), POLL_MS)
    }
    if (!running && timer.current !== null) {
      window.clearInterval(timer.current)
      timer.current = null
    }
    return () => {
      if (timer.current !== null) {
        window.clearInterval(timer.current)
        timer.current = null
      }
    }
  }, [info, refresh])

  async function add() {
    if (!name.trim()) return
    setAdding(true)
    try {
      await addSupplier({ name: name.trim(), site: site.trim(), max_pages: typeof maxPages === 'number' ? maxPages : 3000 })
      setName('')
      setSite('')
      await refresh()
    } catch (e) {
      notifications.show({ color: 'red', title: 'Не удалось добавить поставщика', message: message(e) })
    } finally {
      setAdding(false)
    }
  }

  async function run(id: string, action: () => Promise<unknown>, errorTitle: string) {
    setBusy(id)
    try {
      await action()
      await refresh()
    } catch (e) {
      notifications.show({ color: 'red', title: errorTitle, message: message(e) })
    } finally {
      setBusy(null)
    }
  }

  function remove(supplier: Supplier) {
    if (!window.confirm(`Удалить поставщика «${supplier.name}» и его ${supplier.offers} позиций из индекса?`)) return
    void run(supplier.id, () => removeSupplier(supplier.id), 'Не удалось удалить')
  }

  const suppliers = info?.suppliers ?? []

  return (
    <Stack gap="md">
      <Paper withBorder p="md">
        <Text fw={700}>Индекс цен поставщиков</Text>
        <Text size="sm" c="dimmed">
          {info ? `${info.offers} позиций у ${suppliers.length} поставщиков${info.updated_at ? ` · обновлено ${info.updated_at}` : ''}` : 'загружаем…'}
        </Text>
        <Text size="xs" c="dimmed" mt="xs">
          По сайту поставщика ядро ищет фид YML для Яндекс Маркета, потом карту сайта, потом идёт по ссылкам; цену берёт из разметки
          страниц (schema.org, OpenGraph). Не чаще двух запросов в секунду, robots.txt уважается. Если на сайте нет разметки или он закрыт
          для роботов, загрузите прайс-лист xlsx: нужны колонки с наименованием и ценой, шапку найдём сами. Собранные цены попадают в графу
          «Интернет на дату» вкладки «Себестоимость».
        </Text>
        <Group mt="md" align="flex-end" wrap="wrap">
          <TextInput label="Поставщик" placeholder="Например, Кворус" value={name} onChange={(e) => setName(e.currentTarget.value)} w={240} />
          <TextInput label="Сайт (необязательно)" placeholder="https://example.ru" value={site} onChange={(e) => setSite(e.currentTarget.value)} w={280} />
          <NumberInput
            label="Страниц, не больше"
            value={maxPages}
            onChange={(v) => setMaxPages(typeof v === 'number' ? v : String(v))}
            min={50}
            max={50000}
            step={500}
            w={160}
            hideControls
          />
          <Button leftSection={<IconPlus size={16} />} loading={adding} disabled={!name.trim()} onClick={add}>
            Добавить
          </Button>
        </Group>
      </Paper>

      <Table withTableBorder withColumnBorders fz="sm" verticalSpacing={6}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Поставщик</Table.Th>
            <Table.Th>Источник</Table.Th>
            <Table.Th ta="right">Позиций</Table.Th>
            <Table.Th>Обновлено</Table.Th>
            <Table.Th>Состояние</Table.Th>
            <Table.Th>Действия</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {suppliers.map((s) => (
            <Table.Tr key={s.id}>
              <Table.Td>
                <Text size="sm" fw={500}>
                  {s.name}
                </Text>
                {s.site && (
                  <Anchor href={s.site} target="_blank" rel="noopener noreferrer" size="xs">
                    {s.site}
                  </Anchor>
                )}
              </Table.Td>
              <Table.Td>
                <Text size="xs" c="dimmed" lineClamp={2}>
                  {s.source || '—'}
                </Text>
              </Table.Td>
              <Table.Td ta="right">{s.offers}</Table.Td>
              <Table.Td>{s.collected_at || '—'}</Table.Td>
              <Table.Td>
                <StatusBadge supplier={s} />
              </Table.Td>
              <Table.Td>
                <Group gap={4} wrap="nowrap">
                  {s.status === 'running' ? (
                    <Tooltip label="Остановить обход (собранное сохранится)">
                      <ActionIcon variant="subtle" color="red" onClick={() => void run(s.id, () => stopSupplier(s.id), 'Не удалось остановить')} aria-label="остановить">
                        <IconPlayerStop size={16} />
                      </ActionIcon>
                    </Tooltip>
                  ) : (
                    <Tooltip label={s.site ? 'Обойти сайт и обновить цены' : 'Сайт не указан — загрузите прайс'}>
                      <ActionIcon
                        variant="subtle"
                        disabled={!s.site || busy === s.id}
                        onClick={() => void run(s.id, () => crawlSupplier(s.id), 'Не удалось запустить обход')}
                        aria-label="обновить каталог"
                      >
                        <IconRefresh size={16} />
                      </ActionIcon>
                    </Tooltip>
                  )}
                  <FileButton
                    onChange={(file) => {
                      if (file) void run(s.id, () => uploadSupplierPriceList(s.id, file), 'Не удалось загрузить прайс')
                    }}
                    accept=".xlsx,.xlsm"
                  >
                    {(props) => (
                      <Tooltip label="Загрузить прайс-лист xlsx (заменит цены поставщика)">
                        <ActionIcon {...props} variant="subtle" disabled={s.status === 'running' || busy === s.id} aria-label="загрузить прайс">
                          <IconFileSpreadsheet size={16} />
                        </ActionIcon>
                      </Tooltip>
                    )}
                  </FileButton>
                  <SampleButton supplier={s} />
                  <Tooltip label="Удалить поставщика">
                    <ActionIcon variant="subtle" color="red" onClick={() => remove(s)} disabled={busy === s.id} aria-label="удалить">
                      <IconTrash size={16} />
                    </ActionIcon>
                  </Tooltip>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
          {suppliers.length === 0 && (
            <Table.Tr>
              <Table.Td colSpan={6}>
                <Text size="sm" c="dimmed" ta="center" py="md">
                  Поставщиков пока нет. Добавьте сайт или загрузите прайс-лист.
                </Text>
              </Table.Td>
            </Table.Tr>
          )}
        </Table.Tbody>
      </Table>
    </Stack>
  )
}
