import { Alert, Badge, Button, Collapse, Group, Loader, Paper, ScrollArea, SegmentedControl, Stack, Table, Text, TextInput, rem } from '@mantine/core'
import { Dropzone, MIME_TYPES, PDF_MIME_TYPE } from '@mantine/dropzone'
import { IconArrowRight, IconFileImport, IconSearch, IconX } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'

import { getProject, listProjects, parseDocument, type ProjectInfo, type SummaryItem } from '../api'
import { diffSpecs, type DiffRow, type DiffStatus } from '../compare'
import { useWorkspace } from '../store'

const ACCEPT = [...PDF_MIME_TYPE, MIME_TYPES.xlsx, 'application/vnd.ms-excel.sheet.macroEnabled.12']

interface Side {
  label: string
  summary: SummaryItem[]
}

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

/** Выбор сохранённого объекта — встроенный список с поиском (без вложенной модалки). */
function ObjectPicker({ onPick }: { onPick: (side: Side) => void }) {
  const [search, setSearch] = useState('')
  const [list, setList] = useState<ProjectInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    const t = setTimeout(() => {
      listProjects(search, 0)
        .then((rows) => setList(rows))
        .catch((e) => setError(msg(e)))
        .finally(() => setLoading(false))
    }, 200)
    return () => clearTimeout(t)
  }, [search])

  async function pick(info: ProjectInfo) {
    setLoading(true)
    setError('')
    try {
      const detail = await getProject(info.id)
      const summary = detail.snapshot.documents.flatMap((d) => d.doc.summary)
      onPick({ label: info.title || 'объект', summary })
    } catch (e) {
      setError(msg(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Stack gap="xs" mt="xs">
      <TextInput
        size="xs"
        placeholder="Поиск объекта по названию"
        leftSection={<IconSearch size={14} />}
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
      />
      {error && <Text size="xs" c="red">{error}</Text>}
      <ScrollArea.Autosize mah={200}>
        <Stack gap={4}>
          {loading && <Group gap="xs"><Loader size="xs" /><Text size="xs" c="dimmed">загрузка…</Text></Group>}
          {!loading && list.length === 0 && <Text size="xs" c="dimmed">Сохранённых объектов нет.</Text>}
          {list.map((info) => (
            <Button key={info.id} variant="subtle" size="compact-sm" justify="space-between" fullWidth onClick={() => pick(info)}
              rightSection={<Text size="xs" c="dimmed">{info.positions} поз.</Text>}>
              <Text size="sm" truncate>{info.title || 'без названия'}</Text>
            </Button>
          ))}
        </Stack>
      </ScrollArea.Autosize>
    </Stack>
  )
}

function Slot({ title, value, onChange }: { title: string; value: Side | null; onChange: (s: Side | null) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [picking, setPicking] = useState(false)

  async function onDrop(files: File[]) {
    if (!files.length) return
    setBusy(true)
    setError('')
    try {
      const doc = await parseDocument(files[0])
      onChange({ label: doc.doc_code || doc.file_name || files[0].name, summary: doc.summary })
    } catch (e) {
      setError(msg(e))
    } finally {
      setBusy(false)
    }
  }

  if (value) {
    return (
      <Paper withBorder p="md" style={{ flex: 1, minWidth: 260 }}>
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <div style={{ minWidth: 0 }}>
            <Text size="xs" c="dimmed">{title}</Text>
            <Text fw={600} truncate>{value.label}</Text>
            <Text size="xs" c="dimmed">{value.summary.length} позиций</Text>
          </div>
          <Button variant="subtle" size="compact-xs" onClick={() => onChange(null)}>сменить</Button>
        </Group>
      </Paper>
    )
  }

  return (
    <Paper withBorder p="md" style={{ flex: 1, minWidth: 260 }}>
      <Text fw={600} mb="xs">{title}</Text>
      <Dropzone onDrop={onDrop} accept={ACCEPT} maxSize={100 * 1024 ** 2} multiple={false} loading={busy}>
        <Group justify="center" gap="sm" mih={70} style={{ pointerEvents: 'none' }}>
          <IconFileImport style={{ width: rem(28), height: rem(28) }} stroke={1.5} />
          <Text size="sm">Перетащите файл (PDF/Excel) или нажмите</Text>
        </Group>
      </Dropzone>
      <Button variant="light" size="compact-sm" mt="xs" fullWidth onClick={() => setPicking((v) => !v)}>
        {picking ? 'Скрыть список' : 'или выбрать сохранённый объект'}
      </Button>
      <Collapse expanded={picking}>
        <ObjectPicker onPick={(s) => { onChange(s); setPicking(false) }} />
      </Collapse>
      {error && <Text size="xs" c="red" mt="xs">{error}</Text>}
    </Paper>
  )
}

const STATUS_META: Record<Exclude<DiffStatus, 'unchanged'>, { label: string; color: string }> = {
  changed: { label: 'изменено', color: 'yellow' },
  added: { label: 'добавлено', color: 'green' },
  removed: { label: 'удалено', color: 'red' },
}

function RowCells({ row }: { row: DiffRow }) {
  if (row.status === 'added') {
    return <Text size="sm" c="green.8">+ {row.after?.name}{row.after?.qty != null && ` · ${row.after.qty} ${row.after.unit}`}</Text>
  }
  if (row.status === 'removed') {
    return <Text size="sm" c="red.7" td="line-through">{row.before?.name}{row.before?.qty != null && ` · ${row.before.qty} ${row.before.unit}`}</Text>
  }
  return (
    <Stack gap={2}>
      {row.changes.map((c) => (
        <Text key={c.field} size="sm">
          <Text span c="dimmed">{c.label}: </Text>
          <Text span c="red.7" td="line-through">{c.before || '—'}</Text>
          <IconArrowRight size={12} style={{ margin: '0 4px', verticalAlign: 'middle' }} />
          <Text span c="green.8" fw={500}>{c.after || '—'}</Text>
        </Text>
      ))}
    </Stack>
  )
}

export function CompareView() {
  const title = useWorkspace((s) => s.title)
  const documents = useWorkspace((s) => s.documents)
  const [after, setAfter] = useState<Side | null>(null)
  const [filter, setFilter] = useState<'diff' | 'all'>('diff')

  // «Было» — всегда текущий открытый объект (все его тома вместе), менять нельзя.
  const before = useMemo<Side | null>(() => {
    const summary = documents.flatMap((d) => d.doc.summary)
    const first = documents[0]?.doc
    const label = title || first?.doc_code || first?.file_name || 'текущий объект'
    return summary.length ? { label, summary } : null
  }, [documents, title])

  const diff = useMemo(() => (before && after ? diffSpecs(before.summary, after.summary) : null), [before, after])
  const rows = useMemo(() => {
    if (!diff) return []
    return filter === 'all' ? diff.rows : diff.rows.filter((r) => r.status !== 'unchanged')
  }, [diff, filter])

  return (
    <Stack gap="md">
      <Group grow align="stretch" wrap="wrap">
        <Paper withBorder p="md" style={{ flex: 1, minWidth: 260 }}>
          <Text size="xs" c="dimmed">Было — текущий объект</Text>
          {before ? (
            <>
              <Text fw={600} truncate>{before.label}</Text>
              <Text size="xs" c="dimmed">{before.summary.length} позиций</Text>
            </>
          ) : (
            <Text size="sm" c="dimmed" mt={6}>
              Нет открытого объекта. Откройте спецификацию — она встанет сюда для сравнения с новой версией.
            </Text>
          )}
        </Paper>
        <Slot title="Стало (новая версия)" value={after} onChange={setAfter} />
      </Group>

      {!diff && (
        <Alert variant="light" color="gray">
          {before
            ? 'Загрузите новую версию в «Стало» — файлом или выбором объекта. Позиции сопоставляются по номеру; покажу, что добавлено, удалено и что изменилось (наименование, характеристики, количество).'
            : 'Сначала откройте объект — его спецификация встанет в «Было». Затем загрузите новую версию в «Стало».'}
        </Alert>
      )}

      {diff && (
        <>
          <Group justify="space-between" wrap="wrap">
            <Group gap="xs">
              <Badge color="yellow" variant="light" size="lg">изменено: {diff.counts.changed}</Badge>
              <Badge color="green" variant="light" size="lg">добавлено: {diff.counts.added}</Badge>
              <Badge color="red" variant="light" size="lg">удалено: {diff.counts.removed}</Badge>
              <Badge color="gray" variant="outline" size="lg">без изменений: {diff.counts.unchanged}</Badge>
            </Group>
            <SegmentedControl
              size="xs"
              value={filter}
              onChange={(v) => setFilter(v as 'diff' | 'all')}
              data={[{ label: 'только изменения', value: 'diff' }, { label: 'все позиции', value: 'all' }]}
            />
          </Group>

          {rows.length === 0 ? (
            <Alert color="green" variant="light" icon={<IconX size={16} />}>
              Различий не найдено — версии совпадают по сопоставленным позициям.
            </Alert>
          ) : (
            <ScrollArea.Autosize mah={520}>
              <Table stickyHeader highlightOnHover withTableBorder>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w={90}>№ поз.</Table.Th>
                    <Table.Th w={120}>Что</Table.Th>
                    <Table.Th>Наименование</Table.Th>
                    <Table.Th>Изменение</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {rows.map((row, i) => {
                    const meta = row.status === 'unchanged' ? null : STATUS_META[row.status]
                    return (
                      <Table.Tr key={`${row.pos}-${i}`}>
                        <Table.Td><Text size="sm" ff="monospace">{row.pos}</Text></Table.Td>
                        <Table.Td>{meta ? <Badge color={meta.color} variant="light">{meta.label}</Badge> : <Text size="xs" c="dimmed">без изм.</Text>}</Table.Td>
                        <Table.Td><Text size="sm">{row.name}</Text></Table.Td>
                        <Table.Td>{row.status === 'unchanged' ? <Text size="xs" c="dimmed">—</Text> : <RowCells row={row} />}</Table.Td>
                      </Table.Tr>
                    )
                  })}
                </Table.Tbody>
              </Table>
            </ScrollArea.Autosize>
          )}
        </>
      )}
    </Stack>
  )
}
