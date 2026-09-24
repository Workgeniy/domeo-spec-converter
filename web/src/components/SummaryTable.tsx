import { Table, Text, TextInput, Tooltip } from '@mantine/core'
import { useMemo, useState } from 'react'

import type { SummaryItem } from '../api'
import { formatQty } from './format'

interface Props {
  rows: SummaryItem[]
}

export function SummaryTable({ rows }: Props) {
  const [filter, setFilter] = useState('')

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return rows
    return rows.filter(
      (r) => r.pos.toLowerCase().includes(q) || r.description.toLowerCase().includes(q) || r.section.toLowerCase().includes(q),
    )
  }, [rows, filter])

  return (
    <>
      <TextInput placeholder="Поиск по позиции, описанию, разделу" value={filter} onChange={(e) => setFilter(e.currentTarget.value)} mb="sm" maw={420} />
      <Table.ScrollContainer minWidth={900} mah="70vh">
        <Table striped highlightOnHover withTableBorder withColumnBorders stickyHeader fz="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={48}>№</Table.Th>
              <Table.Th w={90}>№ поз. в ТХ</Table.Th>
              <Table.Th w={160}>Раздел</Table.Th>
              <Table.Th w={220}>Наименование</Table.Th>
              <Table.Th>Технические характеристики</Table.Th>
              <Table.Th w={70}>Ед.</Table.Th>
              <Table.Th w={80}>Кол-во</Table.Th>
              <Table.Th w={110}>Помещений</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {visible.map((r, i) => (
              <Table.Tr key={`${r.pos_key}-${i}`} style={r.warnings.length ? { background: 'var(--mantine-color-yellow-0)' } : undefined}>
                <Table.Td>{i + 1}</Table.Td>
                <Table.Td>{r.pos}</Table.Td>
                <Table.Td>{r.section}</Table.Td>
                <Table.Td>{r.name}</Table.Td>
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
                <Table.Td>{r.unit}</Table.Td>
                <Table.Td ta="right">{formatQty(r.qty)}</Table.Td>
                <Table.Td>
                  <Tooltip
                    multiline
                    w={360}
                    label={r.groups.map((g) => `${g.group || '—'}: ${formatQty(g.qty)}`).join('\n')}
                    styles={{ tooltip: { whiteSpace: 'pre-line' } }}
                  >
                    <Text size="sm" style={{ cursor: 'help' }}>
                      {r.groups.length}
                    </Text>
                  </Tooltip>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </>
  )
}
