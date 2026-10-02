import { Alert, Anchor, Badge, Group, Paper, SimpleGrid, Stack, Table, Text } from '@mantine/core'
import { IconAlertTriangle, IconCircleCheck } from '@tabler/icons-react'

import { crossVolumeDuplicates } from '../duplicates'
import { rowKey, useWorkspace } from '../store'
import { formatQty } from './format'
import { TableScroller } from './TableScroller'

interface Row {
  where: string
  pos: string
  text: string
}

/** Совпадающие позиции между томами: одно наименование в нескольких томах — риск задвоить
 * количество. Рядом — быстрое «Исключить из КП» для лишнего вхождения. */
function DuplicatesAlert() {
  const documents = useWorkspace((s) => s.documents)
  const updateRow = useWorkspace((s) => s.updateRow)
  const groups = crossVolumeDuplicates(documents)
  if (groups.length === 0) return null
  return (
    <Alert color="orange" icon={<IconAlertTriangle size={18} />} title={`Совпадающие позиции между томами: ${groups.length}`}>
      <Text size="sm" mb="xs">
        Одно наименование встречается в нескольких томах — проверьте, не задвоено ли количество. Лишнее вхождение можно исключить
        из КП здесь же; исключённые в сумму не идут.
      </Text>
      <Stack gap="sm">
        {groups.map((g) => (
          <div key={g.key}>
            <Text size="sm" fw={600} lineClamp={2}>
              {g.name}
            </Text>
            <Group gap="xs" mt={2}>
              {g.occurrences.map((o) => (
                <Group key={rowKey(o.rowKey)} gap={4} wrap="nowrap">
                  <Badge variant="light" color={o.excluded ? 'gray' : 'orange'} tt="none" size="sm" style={{ textDecoration: o.excluded ? 'line-through' : undefined }}>
                    {o.docCode}
                    {o.pos ? `, поз. ${o.pos}` : ''} — {o.qty === null ? 'кол-во не указано' : `${formatQty(o.qty)} шт.`}
                  </Badge>
                  <Anchor component="button" type="button" size="xs" onClick={() => updateRow(o.rowKey, { excluded: !o.excluded })}>
                    {o.excluded ? 'вернуть' : 'исключить'}
                  </Anchor>
                </Group>
              ))}
            </Group>
          </div>
        ))}
      </Stack>
    </Alert>
  )
}

export function CheckTable() {
  const documents = useWorkspace((s) => s.documents)

  const rows: Row[] = documents.flatMap(({ doc }) => {
    const code = doc.doc_code || doc.file_name
    return [
      ...doc.warnings.map((w) => ({ where: code, pos: '', text: w })),
      ...doc.pages.flatMap((p) => p.warnings.map((w) => ({ where: `${code}, стр. ${p.number}`, pos: '', text: w }))),
      ...doc.items.flatMap((i) => i.warnings.map((w) => ({ where: `${code}, стр. ${i.page}`, pos: i.pos, text: w }))),
      ...doc.summary.flatMap((s) => s.warnings.map((w) => ({ where: `свод, ${code}`, pos: s.pos, text: w }))),
    ]
  })

  return (
    <Stack gap="md">
      <DuplicatesAlert />
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {documents.map(({ id, doc }) => {
          const src = doc.documents[0]
          const spec = src?.spec_pages ?? doc.pages.filter((p) => p.kind === 'spec').map((p) => p.number)
          const ocr = src?.ocr_pages ?? []
          const skipped = src?.skipped_pages ?? []
          return (
            <Paper key={id} withBorder p="sm">
              <Group justify="space-between" mb={4}>
                <Text fw={600}>{doc.doc_code || doc.file_name}</Text>
                <Group gap={4}>
                  {ocr.length > 0 && <Badge color="grape" size="sm">OCR: {ocr.length}</Badge>}
                  {skipped.length > 0 && <Badge color="red" size="sm">пропущено: {skipped.length}</Badge>}
                </Group>
              </Group>
              <Table fz="xs" withRowBorders={false} verticalSpacing={2}>
                <Table.Tbody>
                  <Table.Tr>
                    <Table.Th style={{ width: 150 }}>Файл</Table.Th>
                    <Table.Td>{doc.file_name}</Table.Td>
                  </Table.Tr>
                  <Table.Tr>
                    <Table.Th>Спецификация</Table.Th>
                    <Table.Td>{doc.spec_title || '—'}</Table.Td>
                  </Table.Tr>
                  <Table.Tr>
                    <Table.Th>Страницы</Table.Th>
                    <Table.Td>
                      со спецификацией {spec.length} из {src?.pages_total ?? doc.pages.length}: {spec.join(', ') || '—'}
                    </Table.Td>
                  </Table.Tr>
                  {ocr.length > 0 && (
                    <Table.Tr>
                      <Table.Th>Распознано OCR</Table.Th>
                      <Table.Td>{ocr.join(', ')}</Table.Td>
                    </Table.Tr>
                  )}
                  {skipped.length > 0 && (
                    <Table.Tr>
                      <Table.Th>Скан без OCR</Table.Th>
                      <Table.Td>{skipped.join(', ')}</Table.Td>
                    </Table.Tr>
                  )}
                  <Table.Tr>
                    <Table.Th>Строк / позиций</Table.Th>
                    <Table.Td>
                      {doc.items.length} / {doc.summary.length}
                    </Table.Td>
                  </Table.Tr>
                </Table.Tbody>
              </Table>
            </Paper>
          )
        })}
      </SimpleGrid>

      {rows.length === 0 ? (
        <Alert color="green" icon={<IconCircleCheck size={18} />}>
          Замечаний нет: все строки прочитаны с позицией, единицей и количеством.
        </Alert>
      ) : (
        <TableScroller minWidth={700}>
          <Table striped withTableBorder withColumnBorders fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th style={{ width: 220 }}>Где</Table.Th>
                <Table.Th style={{ width: 100 }}>Позиция</Table.Th>
                <Table.Th>Замечание</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((r, i) => (
                <Table.Tr key={i}>
                  <Table.Td>{r.where}</Table.Td>
                  <Table.Td>{r.pos}</Table.Td>
                  <Table.Td>{r.text}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </TableScroller>
      )}
    </Stack>
  )
}
