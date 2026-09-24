import { Group, Pagination, Select, Table, Text, TextInput } from '@mantine/core'
import { useEffect, useMemo, useState } from 'react'

import { useWorkspace } from '../store'
import { formatQty } from './format'

const PAGE_SIZE = 50

export function DetailTable() {
  const documents = useWorkspace((s) => s.documents)
  const [filter, setFilter] = useState('')
  const [docCode, setDocCode] = useState<string | null>(null)
  const [room, setRoom] = useState<string | null>(null)
  const [page, setPage] = useState(1)

  const items = useMemo(() => documents.flatMap((d) => d.doc.items), [documents])
  const docOptions = useMemo(() => [...new Set(items.map((i) => i.source_doc).filter(Boolean))], [items])
  const roomOptions = useMemo(
    () => [...new Set(items.filter((i) => !docCode || i.source_doc === docCode).map((i) => i.group).filter(Boolean))],
    [items, docCode],
  )

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase()
    return items.filter((r) => {
      if (docCode && r.source_doc !== docCode) return false
      if (room && r.group !== room) return false
      if (!q) return true
      return r.pos.toLowerCase().includes(q) || r.description.toLowerCase().includes(q) || r.group.toLowerCase().includes(q) || r.note.toLowerCase().includes(q)
    })
  }, [items, filter, docCode, room])

  const pages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE))
  useEffect(() => setPage(1), [filter, docCode, room])
  const slice = visible.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  return (
    <>
      <Group gap="sm" mb="sm" wrap="wrap">
        <TextInput placeholder="Поиск по позиции, описанию, помещению" value={filter} onChange={(e) => setFilter(e.currentTarget.value)} w={320} size="sm" />
        {docOptions.length > 1 && (
          <Select placeholder="Документ" data={docOptions} value={docCode} onChange={(v) => setDocCode(v === null ? null : String(v))} clearable w={220} size="sm" />
        )}
        <Select placeholder="Помещение / раздел" data={roomOptions} value={room} onChange={(v) => setRoom(v === null ? null : String(v))} clearable searchable w={340} size="sm" />
        {pages > 1 && <Pagination total={pages} value={page} onChange={setPage} size="sm" />}
        <Text size="sm" c="dimmed">
          {pages > 1
            ? `строки ${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, visible.length)} из ${visible.length}`
            : `Строк: ${visible.length}`}
        </Text>
      </Group>
      {/* Без ограничения высоты: прокручивается вся страница, а не таблица внутри страницы. */}
      <Table.ScrollContainer minWidth={1300}>
        <Table striped highlightOnHover withTableBorder withColumnBorders fz="sm" layout="fixed">
          <colgroup>
            {[...(docOptions.length > 1 ? [130] : []), 56, 220, 80, null, 160, 140, 64, 70, 180].map((w, i) => (
              <col key={i} style={w ? { width: w } : undefined} />
            ))}
          </colgroup>
          <Table.Thead>
            <Table.Tr>
              {docOptions.length > 1 && <Table.Th>Документ</Table.Th>}
              <Table.Th>Стр.</Table.Th>
              <Table.Th>Помещение / раздел</Table.Th>
              <Table.Th>Поз.</Table.Th>
              <Table.Th>Наименование и характеристика</Table.Th>
              <Table.Th>Тип, марка</Table.Th>
              <Table.Th>Изготовитель</Table.Th>
              <Table.Th>Ед.</Table.Th>
              <Table.Th>Кол-во</Table.Th>
              <Table.Th>Примечание</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {slice.map((r) => (
              <Table.Tr key={`${r.source_doc}:${r.id}`} style={r.warnings.length ? { background: 'var(--mantine-color-yellow-0)' } : undefined}>
                {docOptions.length > 1 && <Table.Td>{r.source_doc}</Table.Td>}
                <Table.Td>{r.page}</Table.Td>
                <Table.Td>
                  <Text size="sm" lineClamp={2} title={r.group}>
                    {r.group}
                  </Text>
                </Table.Td>
                <Table.Td>{r.pos}</Table.Td>
                <Table.Td>
                  <Text size="sm" lineClamp={3} title={r.description}>
                    {r.description}
                  </Text>
                  {r.warnings.length > 0 && (
                    <Text size="xs" c="orange.8">
                      {r.warnings.join('; ')}
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>{r.type_mark}</Table.Td>
                <Table.Td>{r.manufacturer}</Table.Td>
                <Table.Td>{r.unit}</Table.Td>
                <Table.Td ta="right">{r.qty === null ? r.qty_raw : formatQty(r.qty)}</Table.Td>
                <Table.Td>
                  <Text size="sm" lineClamp={2} title={r.note}>
                    {r.note}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {pages > 1 && (
        <Group justify="center" mt="sm">
          <Pagination total={pages} value={page} onChange={setPage} size="sm" />
        </Group>
      )}
    </>
  )
}
