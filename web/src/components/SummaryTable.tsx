import { Autocomplete, Button, Checkbox, Group, Pagination, Paper, SegmentedControl, Table, Text, TextInput } from '@mantine/core'
import { IconArrowBackUp, IconTrash } from '@tabler/icons-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { SECTIONS } from '../sections'
import { kpTotals } from '../kp'
import { useWorkspace, type RowKey, type SummaryRow } from '../store'
import { formatMoney } from './format'
import { SummaryRowView } from './SummaryRow'

type Mode = 'all' | 'warnings' | 'noprice' | 'noted' | 'excluded'

// Ширины граф в пикселях; null — «Технические характеристики» забирают остаток.
const SUMMARY_COLUMNS: (number | null)[] = [36, 46, 96, 170, 190, null, 60, 76, 60, 116, 110, 120, 44]
const PAGE_SIZE = 50

interface FlatRow {
  key: RowKey
  id: string
  row: SummaryRow
}

export function SummaryTable() {
  const documents = useWorkspace((s) => s.documents)
  const kp = useWorkspace((s) => s.kp)
  const updateRow = useWorkspace((s) => s.updateRow)
  const updateRows = useWorkspace((s) => s.updateRows)

  const [filter, setFilter] = useState('')
  const [mode, setMode] = useState<Mode>('all')
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [bulkSection, setBulkSection] = useState('')
  const [page, setPage] = useState(1)

  const rows = useMemo<FlatRow[]>(
    () => documents.flatMap((d) => d.doc.summary.map((row, index) => ({ key: { docId: d.id, index }, id: `${d.id}:${index}`, row }))),
    [documents],
  )

  const sections = useMemo(() => {
    const present = new Set(rows.map((r) => r.row.section).filter(Boolean))
    return [...SECTIONS, ...[...present].filter((s) => !SECTIONS.includes(s))]
  }, [rows])

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase()
    return rows.filter(({ row }) => {
      if (mode === 'excluded') {
        if (!row.excluded) return false
      } else if (row.excluded) return false
      if (mode === 'warnings' && row.warnings.length === 0) return false
      if (mode === 'noprice' && row.price !== null) return false
      if (mode === 'noted' && !row.note) return false
      if (!q) return true
      return (
        row.pos.toLowerCase().includes(q) ||
        row.name.toLowerCase().includes(q) ||
        row.description.toLowerCase().includes(q) ||
        row.section.toLowerCase().includes(q) ||
        row.note.toLowerCase().includes(q)
      )
    })
  }, [rows, filter, mode])

  // Постранично: 200 строк с полями ввода на одной странице рисуются несколько секунд.
  const pages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE))
  useEffect(() => setPage(1), [filter, mode])
  const currentPage = Math.min(page, pages)
  const pageRows = visible.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

  const totals = useMemo(() => {
    const active = rows.filter((r) => !r.row.excluded).map((r) => r.row)
    const t = kpTotals(active, kp)
    return { positions: active.length, excluded: rows.length - active.length, priced: t.priced, sum: t.total }
  }, [rows, kp])

  const onToggle = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const allVisibleSelected = visible.length > 0 && visible.every((r) => selected.has(r.id))
  function toggleAllVisible() {
    setSelected((prev) => {
      const next = new Set(prev)
      if (allVisibleSelected) visible.forEach((r) => next.delete(r.id))
      else visible.forEach((r) => next.add(r.id))
      return next
    })
  }

  const selectedKeys = rows.filter((r) => selected.has(r.id)).map((r) => r.key)
  function applyBulk(patch: Partial<SummaryRow>) {
    updateRows(selectedKeys, patch)
    setSelected(new Set())
  }

  const showDoc = documents.length > 1

  return (
    <>
      <Paper withBorder p="sm" mb="sm">
        <Group gap="sm" align="flex-end" wrap="wrap">
          <TextInput placeholder="Поиск по позиции, описанию, разделу, примечанию" value={filter} onChange={(e) => setFilter(e.currentTarget.value)} w={340} size="sm" />
          <SegmentedControl
            size="xs"
            value={mode}
            onChange={(v) => setMode(v as Mode)}
            data={[
              { value: 'all', label: `Все (${totals.positions})` },
              { value: 'warnings', label: 'С замечаниями' },
              { value: 'noprice', label: 'Без цены' },
              { value: 'noted', label: 'С примечанием' },
              { value: 'excluded', label: `Исключённые (${totals.excluded})` },
            ]}
          />
        </Group>
        <Group gap="sm" align="center" mt="sm" wrap="wrap">
          {pages > 1 && <Pagination total={pages} value={currentPage} onChange={setPage} size="sm" />}
          <Text size="sm" c="dimmed">
            {pages > 1 && `строки ${(currentPage - 1) * PAGE_SIZE + 1}–${Math.min(currentPage * PAGE_SIZE, visible.length)} из ${visible.length} · `}
            Выбрано: {selectedKeys.length}
          </Text>
          <Autocomplete size="xs" placeholder="раздел для выбранных" data={sections} value={bulkSection} onChange={setBulkSection} w={300} limit={20} disabled={selectedKeys.length === 0} />
          <Button size="xs" variant="light" disabled={selectedKeys.length === 0 || !bulkSection.trim()} onClick={() => applyBulk({ section: bulkSection.trim() })}>
            Назначить раздел
          </Button>
          <Button size="xs" variant="light" color="red" leftSection={<IconTrash size={14} />} disabled={selectedKeys.length === 0} onClick={() => applyBulk({ excluded: true })}>
            Исключить из КП
          </Button>
          <Button size="xs" variant="light" leftSection={<IconArrowBackUp size={14} />} disabled={selectedKeys.length === 0} onClick={() => applyBulk({ excluded: false })}>
            Вернуть
          </Button>
        </Group>
      </Paper>

      {/* Без ограничения высоты: прокручивается вся страница, а не таблица внутри страницы. */}
      <Table.ScrollContainer minWidth={1640}>
        <Table striped={false} highlightOnHover withTableBorder withColumnBorders fz="sm" layout="fixed" verticalSpacing={4}>
          {/* Ширины через colgroup: в фиксированной раскладке ширины на th браузер здесь не учитывает. */}
          <colgroup>
            {SUMMARY_COLUMNS.map((w, i) => (
              <col key={i} style={w ? { width: w } : undefined} />
            ))}
          </colgroup>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>
                <Checkbox size="xs" checked={allVisibleSelected} indeterminate={!allVisibleSelected && visible.some((r) => selected.has(r.id))} onChange={toggleAllVisible} aria-label="выбрать все" />
              </Table.Th>
              <Table.Th>№</Table.Th>
              <Table.Th>№ поз. в ТХ</Table.Th>
              <Table.Th>Раздел</Table.Th>
              <Table.Th>Наименование</Table.Th>
              <Table.Th>Технические характеристики</Table.Th>
              <Table.Th>Ед.</Table.Th>
              <Table.Th>Кол-во</Table.Th>
              <Table.Th>Помещ.</Table.Th>
              <Table.Th>Цена (база), с НДС</Table.Th>
              <Table.Th>Цена в КП, с НДС</Table.Th>
              <Table.Th>Сумма в КП</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {pageRows.map((r, i) => (
              <SummaryRowView
                key={r.id}
                number={(currentPage - 1) * PAGE_SIZE + i + 1}
                row={r.row}
                rowKey={r.key}
                selected={selected.has(r.id)}
                showDoc={showDoc}
                sections={sections}
                kp={kp}
                onToggle={onToggle}
                onChange={updateRow}
              />
            ))}
            {visible.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={13}>
                  <Text size="sm" c="dimmed" ta="center" py="md">
                    Нет строк под этот фильтр
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
          <Table.Tfoot>
            <Table.Tr>
              <Table.Td colSpan={9}>
                <Text size="sm" fw={600}>
                  Позиций в КП: {totals.positions}
                  {totals.excluded > 0 && ` (исключено ${totals.excluded})`} · с ценой: {totals.priced}
                </Text>
              </Table.Td>
              <Table.Td colSpan={2}>
                <Text size="sm" fw={600} ta="right">
                  Итого по КП, с НДС
                </Text>
              </Table.Td>
              <Table.Td>
                <Text size="sm" fw={700} ta="right">
                  {formatMoney(totals.sum)}
                </Text>
              </Table.Td>
              <Table.Td />
            </Table.Tr>
          </Table.Tfoot>
        </Table>
      </Table.ScrollContainer>
      <Group justify="space-between" mt={6}>
        <Text size="xs" c="dimmed">
          Жёлтые строки — с замечаниями разбора; наведите на число в графе «Помещ.», чтобы увидеть раскладку по помещениям.
        </Text>
        {pages > 1 && <Pagination total={pages} value={currentPage} onChange={setPage} size="sm" />}
      </Group>
    </>
  )
}
