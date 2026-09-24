import { Alert, Stack, Table, Text } from '@mantine/core'
import { IconCircleCheck } from '@tabler/icons-react'

import type { ParsedDocument } from '../api'

interface Props {
  doc: ParsedDocument
}

interface Row {
  where: string
  pos: string
  text: string
}

export function CheckTable({ doc }: Props) {
  const rows: Row[] = [
    ...doc.warnings.map((w) => ({ where: 'документ', pos: '', text: w })),
    ...doc.pages.flatMap((p) => p.warnings.map((w) => ({ where: `стр. ${p.number}`, pos: '', text: w }))),
    ...doc.items.flatMap((i) => i.warnings.map((w) => ({ where: `стр. ${i.page}`, pos: i.pos, text: w }))),
    ...doc.summary.flatMap((s) => s.warnings.map((w) => ({ where: 'свод', pos: s.pos, text: w }))),
  ]
  const specPages = doc.pages.filter((p) => p.kind === 'spec').map((p) => p.number)
  const ocrPages = doc.pages.filter((p) => p.source === 'ocr').map((p) => p.number)
  const skipped = doc.pages.filter((p) => p.source === 'skipped').map((p) => p.number)

  return (
    <Stack gap="md">
      <Table withTableBorder fz="sm" maw={900}>
        <Table.Tbody>
          <Table.Tr>
            <Table.Th w={260}>Файл</Table.Th>
            <Table.Td>{doc.file_name}</Table.Td>
          </Table.Tr>
          <Table.Tr>
            <Table.Th>Шифр документа</Table.Th>
            <Table.Td>{doc.doc_code}</Table.Td>
          </Table.Tr>
          <Table.Tr>
            <Table.Th>Спецификация</Table.Th>
            <Table.Td>{doc.spec_title || '—'}</Table.Td>
          </Table.Tr>
          <Table.Tr>
            <Table.Th>Страницы со спецификацией</Table.Th>
            <Table.Td>{specPages.join(', ') || '—'}</Table.Td>
          </Table.Tr>
          <Table.Tr>
            <Table.Th>Распознано OCR</Table.Th>
            <Table.Td>{ocrPages.join(', ') || '—'}</Table.Td>
          </Table.Tr>
          <Table.Tr>
            <Table.Th>Пропущено (скан без OCR)</Table.Th>
            <Table.Td>{skipped.join(', ') || '—'}</Table.Td>
          </Table.Tr>
        </Table.Tbody>
      </Table>

      {rows.length === 0 ? (
        <Alert color="green" icon={<IconCircleCheck size={18} />}>
          Замечаний нет: все строки прочитаны с позицией, единицей и количеством.
        </Alert>
      ) : (
        <Table.ScrollContainer minWidth={700} mah="60vh">
          <Table striped withTableBorder withColumnBorders stickyHeader fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={100}>Где</Table.Th>
                <Table.Th w={100}>Позиция</Table.Th>
                <Table.Th>Замечание</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((r, i) => (
                <Table.Tr key={i}>
                  <Table.Td>{r.where}</Table.Td>
                  <Table.Td>{r.pos}</Table.Td>
                  <Table.Td>
                    <Text size="sm">{r.text}</Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  )
}
