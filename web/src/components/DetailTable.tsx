import { Table, Text, TextInput } from '@mantine/core'
import { useMemo, useState } from 'react'

import type { SpecItem } from '../api'
import { formatQty } from './format'

interface Props {
  rows: SpecItem[]
}

export function DetailTable({ rows }: Props) {
  const [filter, setFilter] = useState('')

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return rows
    return rows.filter(
      (r) => r.pos.toLowerCase().includes(q) || r.description.toLowerCase().includes(q) || r.group.toLowerCase().includes(q),
    )
  }, [rows, filter])

  return (
    <>
      <TextInput placeholder="Поиск по позиции, описанию, помещению" value={filter} onChange={(e) => setFilter(e.currentTarget.value)} mb="sm" maw={420} />
      <Table.ScrollContainer minWidth={1000} mah="70vh">
        <Table striped highlightOnHover withTableBorder withColumnBorders stickyHeader fz="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={60}>Стр.</Table.Th>
              <Table.Th w={220}>Помещение / раздел</Table.Th>
              <Table.Th w={80}>Поз.</Table.Th>
              <Table.Th>Наименование и характеристика</Table.Th>
              <Table.Th w={160}>Тип, марка</Table.Th>
              <Table.Th w={140}>Изготовитель</Table.Th>
              <Table.Th w={70}>Ед.</Table.Th>
              <Table.Th w={70}>Кол-во</Table.Th>
              <Table.Th w={180}>Примечание</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {visible.map((r) => (
              <Table.Tr key={r.id} style={r.warnings.length ? { background: 'var(--mantine-color-yellow-0)' } : undefined}>
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
                    <Text size="xs" c="orange">
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
    </>
  )
}
