import {
  ActionIcon,
  Anchor,
  Autocomplete,
  Badge,
  Button,
  FileButton,
  Group,
  Modal,
  NumberInput,
  Paper,
  Popover,
  ScrollArea,
  Stack,
  Table,
  TagsInput,
  Text,
  Textarea,
  TextInput,
  Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconEye, IconFileSpreadsheet, IconMail, IconPlayerStop, IconPlus, IconRefresh, IconTags, IconTrash } from '@tabler/icons-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  addSupplier,
  crawlSupplier,
  getSuppliers,
  removeSupplier,
  sampleSupplierOffers,
  stopSupplier,
  updateSupplier,
  updateSupplierSettings,
  uploadSupplierPriceList,
  type Supplier,
  type SupplierIndexInfo,
  type SupplierOffer,
} from '../api'
import { SECTIONS } from '../sections'
import { useWorkspace } from '../store'
import { formatMoney } from './format'

const POLL_MS = 3000

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

/** Письмо поставщику: прайсы по разделам, срок действия цен, плановое изменение — то, что нужно для индексации. */
export function requestLetter(sections: string[]): string {
  const list = sections.length > 0 ? sections.map((s) => `— ${s}`).join('\n') : '— (укажите разделы)'
  return [
    'Здравствуйте!',
    '',
    'Просим направить актуальный прайс-лист по разделам:',
    list,
    '',
    'По каждому разделу просим указать:',
    '1. Срок действия цен.',
    '2. Планируемое изменение цен и его дату, если оно известно.',
    '3. Условия фиксации цены на период поставки (предоплата, договор).',
    '',
    'Удобный формат — xlsx с колонками «Наименование», «Артикул», «Ед. изм.», «Цена с НДС».',
    '',
    'Спасибо!',
  ].join('\n')
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
              {o.section && (
                <Text span c="dimmed">
                  {' '}
                  · {o.section}
                </Text>
              )}
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

function SectionsEditor({ supplier, suggestions, onSave }: { supplier: Supplier; suggestions: string[]; onSave: (sections: string[]) => Promise<void> }) {
  const [opened, setOpened] = useState(false)
  const [value, setValue] = useState<string[]>(supplier.sections)
  const [saving, setSaving] = useState(false)

  useEffect(() => setValue(supplier.sections), [supplier.sections])

  async function save() {
    setSaving(true)
    try {
      await onSave(value)
      setOpened(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Popover opened={opened} onChange={setOpened} width={420} shadow="md" withArrow transitionProps={{ duration: 0 }}>
      <Popover.Target>
        <Tooltip label="Разделы КП, которые закрывает поставщик">
          <ActionIcon variant="subtle" onClick={() => setOpened((v) => !v)} aria-label="разделы">
            <IconTags size={16} />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs">
          <TagsInput label="Разделы" data={suggestions} value={value} onChange={setValue} placeholder="Мебель, Пищеблок…" />
          <Group justify="flex-end">
            <Button size="xs" loading={saving} onClick={save}>
              Сохранить
            </Button>
          </Group>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  )
}

export function SuppliersPanel() {
  const objectSections = useWorkspace((s) => Array.from(new Set(s.documents.flatMap((d) => d.doc.summary).map((r) => r.section.trim()).filter(Boolean))))
  const [info, setInfo] = useState<SupplierIndexInfo | null>(null)
  const [name, setName] = useState('')
  const [site, setSite] = useState('')
  const [sections, setSections] = useState<string[]>([])
  const [maxPages, setMaxPages] = useState<number | string>(3000)
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [autocrawl, setAutocrawl] = useState<number | string>(300)
  const [minShops, setMinShops] = useState<number | string>(3)
  const [settingsTouched, setSettingsTouched] = useState(false)
  const [savingSettings, setSavingSettings] = useState(false)
  const [pendingUpload, setPendingUpload] = useState<{ supplier: Supplier; file: File } | null>(null)
  const [uploadSection, setUploadSection] = useState('')
  const [letter, setLetter] = useState<{ supplier: Supplier; text: string } | null>(null)
  const timer = useRef<number | null>(null)

  const suggestions = useMemo(() => Array.from(new Set([...SECTIONS, ...objectSections, ...(info?.suppliers.flatMap((s) => s.sections) ?? [])])), [objectSections, info])

  const refresh = useCallback(async () => {
    try {
      const next = await getSuppliers()
      setInfo(next)
      if (!settingsTouched) {
        setAutocrawl(next.autocrawl_pages)
        setMinShops(next.min_shops)
      }
    } catch (e) {
      notifications.show({ color: 'red', title: 'Поставщики', message: message(e) })
    }
  }, [settingsTouched])

  async function saveSettings() {
    setSavingSettings(true)
    try {
      const next = await updateSupplierSettings({
        autocrawl_pages: typeof autocrawl === 'number' ? autocrawl : 0,
        min_shops: typeof minShops === 'number' ? minShops : 3,
      })
      setInfo(next)
      setAutocrawl(next.autocrawl_pages)
      setMinShops(next.min_shops)
      setSettingsTouched(false)
      notifications.show({
        color: 'green',
        message: `Интернет опрашивается, пока меньше ${next.min_shops} магазинов; найденные сайты ${next.autocrawl_pages > 0 ? `обходятся до ${next.autocrawl_pages} страниц` : 'не обходятся'}`,
      })
    } catch (e) {
      notifications.show({ color: 'red', title: 'Не удалось сохранить настройку', message: message(e) })
    } finally {
      setSavingSettings(false)
    }
  }

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
      await addSupplier({ name: name.trim(), site: site.trim(), max_pages: typeof maxPages === 'number' ? maxPages : 3000, sections })
      setName('')
      setSite('')
      setSections([])
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

  async function confirmUpload() {
    if (!pendingUpload) return
    const { supplier, file } = pendingUpload
    setPendingUpload(null)
    await run(supplier.id, () => uploadSupplierPriceList(supplier.id, file, uploadSection), 'Не удалось загрузить прайс')
    notifications.show({ color: 'green', message: uploadSection.trim() ? `Прайс раздела «${uploadSection.trim()}» загружен` : 'Прайс загружен' })
  }

  function openLetter(supplier: Supplier) {
    const forSections = supplier.sections.length > 0 ? supplier.sections : objectSections.length > 0 ? objectSections : SECTIONS
    setLetter({ supplier, text: requestLetter(forSections) })
  }

  async function copyLetter() {
    if (!letter) return
    try {
      await navigator.clipboard.writeText(letter.text)
      notifications.show({ color: 'green', message: 'Текст запроса скопирован' })
    } catch {
      notifications.show({ color: 'yellow', message: 'Не удалось скопировать автоматически — выделите текст и скопируйте вручную' })
    }
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
          Поставщики появляются здесь двумя путями. Автопоиск: при поиске цен во вкладке «Себестоимость» позиция, по которой в индексе
          меньше заданного числа магазинов, ищется в интернете{info?.search_engine ? ` (${info.search_engine}, без ключей и оплаты)` : ''},
          найденные магазины и их цены попадают сюда сами, а их каталоги встают в очередь на обход. Вручную: сайт или прайс-лист xlsx (нужны
          колонки с наименованием и ценой, шапку найдём сами); прайс можно грузить по разделам — каждый файл заменяет цены только своего
          раздела. По сайту ядро ищет фид YML, потом карту сайта, потом идёт по ссылкам; цену берёт из разметки страниц. Не чаще двух
          запросов в секунду, robots.txt уважается. Кнопка с конвертом даёт текст запроса поставщику: прайсы по разделам, срок действия цен и
          плановое изменение — это нужно для индексации.
        </Text>
        <Group mt="sm" align="flex-end" wrap="wrap">
          <NumberInput
            label="Искать в интернете, пока по позиции меньше магазинов"
            description="Сколько разных магазинов считать картиной рынка"
            value={minShops}
            onChange={(v) => {
              setMinShops(typeof v === 'number' ? v : String(v))
              setSettingsTouched(true)
            }}
            min={1}
            max={10}
            w={300}
          />
          <NumberInput
            label="Обходить найденные автопоиском сайты, страниц"
            description="0 — не обходить, только страницы из поиска"
            value={autocrawl}
            onChange={(v) => {
              setAutocrawl(typeof v === 'number' ? v : String(v))
              setSettingsTouched(true)
            }}
            min={0}
            max={50000}
            step={100}
            w={300}
            hideControls
          />
          <Button variant="default" loading={savingSettings} disabled={!info || !settingsTouched} onClick={saveSettings}>
            Сохранить
          </Button>
          {info && info.queued > 0 && (
            <Text size="sm" c="dimmed">
              в очереди на обход: {info.queued}
            </Text>
          )}
          {info && !info.search_engine && (
            <Text size="sm" c="dimmed">
              автопоиск выключен (WEB_SEARCH_ENGINE=off или нет библиотеки ddgs)
            </Text>
          )}
        </Group>
        <Group mt="md" align="flex-end" wrap="wrap">
          <TextInput label="Поставщик" placeholder="Например, Кворус" value={name} onChange={(e) => setName(e.currentTarget.value)} w={220} />
          <TextInput label="Сайт (необязательно)" placeholder="https://example.ru" value={site} onChange={(e) => setSite(e.currentTarget.value)} w={240} />
          <TagsInput label="Разделы" placeholder="Мебель, Пищеблок…" data={suggestions} value={sections} onChange={setSections} w={300} />
          <NumberInput
            label="Страниц, не больше"
            value={maxPages}
            onChange={(v) => setMaxPages(typeof v === 'number' ? v : String(v))}
            min={50}
            max={50000}
            step={500}
            w={150}
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
            <Table.Th>Разделы</Table.Th>
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
                <Group gap={6} wrap="nowrap">
                  <Text size="sm" fw={500}>
                    {s.name}
                  </Text>
                  {s.discovered && (
                    <Tooltip label={s.query ? `Нашёлся автопоиском по запросу «${s.query}»` : 'Нашёлся автопоиском'} multiline w={320}>
                      <Badge size="xs" variant="light" color="grape" style={{ cursor: 'help' }}>
                        автопоиск
                      </Badge>
                    </Tooltip>
                  )}
                </Group>
                {s.site && (
                  <Anchor href={s.site} target="_blank" rel="noopener noreferrer" size="xs">
                    {s.site}
                  </Anchor>
                )}
                {s.discovered && !s.crawled && s.status !== 'running' && (
                  <Text size="xs" c="dimmed">
                    пока только страницы из поиска
                  </Text>
                )}
              </Table.Td>
              <Table.Td>
                <Group gap={4} wrap="wrap">
                  {s.sections.map((section) => (
                    <Badge key={section} size="xs" variant="outline">
                      {section}
                    </Badge>
                  ))}
                  {s.sections.length === 0 && (
                    <Text size="xs" c="dimmed">
                      —
                    </Text>
                  )}
                </Group>
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
                      if (file) {
                        setUploadSection(s.sections[0] ?? '')
                        setPendingUpload({ supplier: s, file })
                      }
                    }}
                    accept=".xlsx,.xlsm"
                  >
                    {(props) => (
                      <Tooltip label="Загрузить прайс-лист xlsx (весь или по разделу)">
                        <ActionIcon {...props} variant="subtle" disabled={s.status === 'running' || busy === s.id} aria-label="загрузить прайс">
                          <IconFileSpreadsheet size={16} />
                        </ActionIcon>
                      </Tooltip>
                    )}
                  </FileButton>
                  <SectionsEditor
                    supplier={s}
                    suggestions={suggestions}
                    onSave={(next) => run(s.id, () => updateSupplier(s.id, { sections: next }), 'Не удалось сохранить разделы')}
                  />
                  <Tooltip label="Текст запроса поставщику: прайсы по разделам и индексация">
                    <ActionIcon variant="subtle" onClick={() => openLetter(s)} aria-label="запрос поставщику">
                      <IconMail size={16} />
                    </ActionIcon>
                  </Tooltip>
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
              <Table.Td colSpan={7}>
                <Text size="sm" c="dimmed" ta="center" py="md">
                  Поставщиков пока нет. Добавьте сайт или загрузите прайс-лист.
                </Text>
              </Table.Td>
            </Table.Tr>
          )}
        </Table.Tbody>
      </Table>

      <Modal opened={pendingUpload !== null} onClose={() => setPendingUpload(null)} title="Прайс-лист поставщика" transitionProps={{ duration: 0 }}>
        <Stack gap="sm">
          <Text size="sm">
            {pendingUpload?.supplier.name}: файл {pendingUpload?.file.name}
          </Text>
          <Autocomplete
            label="Раздел прайса (необязательно)"
            description="С разделом файл заменит цены только этого раздела; без раздела — все цены поставщика"
            data={suggestions}
            value={uploadSection}
            onChange={setUploadSection}
            placeholder="Мебель"
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setPendingUpload(null)}>
              Отмена
            </Button>
            <Button onClick={() => void confirmUpload()}>Загрузить</Button>
          </Group>
        </Stack>
      </Modal>

      <Modal opened={letter !== null} onClose={() => setLetter(null)} title={letter ? `Запрос поставщику «${letter.supplier.name}»` : ''} size="lg" transitionProps={{ duration: 0 }}>
        <Stack gap="sm">
          <Textarea value={letter?.text ?? ''} onChange={(e) => letter && setLetter({ ...letter, text: e.currentTarget.value })} autosize minRows={12} />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setLetter(null)}>
              Закрыть
            </Button>
            <Button onClick={() => void copyLetter()}>Скопировать</Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
