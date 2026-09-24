import { Alert, Badge, Group, Paper, SimpleGrid, Stack, Table, Text } from '@mantine/core'
import { IconCircleCheck } from '@tabler/icons-react'

import { useWorkspace } from '../store'

interface Row {
  where: string
  pos: string
  text: string
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
        <Table.ScrollContainer minWidth={700}>
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
        </Table.ScrollContainer>
      )}
    </Stack>
  )
}
