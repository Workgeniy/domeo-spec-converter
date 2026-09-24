import { Badge, Button, Group, Paper, Stack, Tabs, Text, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconArrowLeft, IconDownload } from '@tabler/icons-react'
import { useMemo, useState } from 'react'

import { exportExcel, type ParsedDocument } from '../api'
import { CheckTable } from './CheckTable'
import { DetailTable } from './DetailTable'
import { SummaryTable } from './SummaryTable'

interface Props {
  doc: ParsedDocument
  onReset: () => void
}

export function ResultView({ doc, onReset }: Props) {
  const [downloading, setDownloading] = useState(false)

  const stats = useMemo(() => {
    const spec = doc.pages.filter((p) => p.kind === 'spec')
    const ocr = doc.pages.filter((p) => p.source === 'ocr').length
    const skipped = doc.pages.filter((p) => p.source === 'skipped').length
    const warnings =
      doc.warnings.length +
      doc.pages.reduce((n, p) => n + p.warnings.length, 0) +
      doc.items.reduce((n, i) => n + i.warnings.length, 0) +
      doc.summary.reduce((n, s) => n + s.warnings.length, 0)
    return { spec: spec.length, total: doc.pages.length, ocr, skipped, warnings }
  }, [doc])

  async function download() {
    setDownloading(true)
    try {
      const { blob, fileName } = await exportExcel(doc)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = fileName
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      notifications.show({ color: 'red', title: 'Не удалось сформировать Excel', message: String(e) })
    } finally {
      setDownloading(false)
    }
  }

  return (
    <Stack gap="md">
      <Paper withBorder p="md">
        <Group justify="space-between" align="flex-start">
          <div>
            <Title order={4}>{doc.doc_code || doc.file_name}</Title>
            {doc.title && (
              <Text size="sm" c="dimmed">
                {doc.title}
              </Text>
            )}
            <Group gap="xs" mt="xs">
              <Badge variant="light">
                страниц со спецификацией: {stats.spec} из {stats.total}
              </Badge>
              <Badge variant="light">строк: {doc.items.length}</Badge>
              <Badge variant="light">позиций в своде: {doc.summary.length}</Badge>
              {stats.ocr > 0 && <Badge color="grape">OCR: {stats.ocr} стр.</Badge>}
              {stats.skipped > 0 && <Badge color="red">пропущено сканов: {stats.skipped}</Badge>}
              <Badge color={stats.warnings ? 'yellow' : 'green'}>замечаний: {stats.warnings}</Badge>
            </Group>
          </div>
          <Group>
            <Button variant="default" leftSection={<IconArrowLeft size={16} />} onClick={onReset}>
              Другой файл
            </Button>
            <Button leftSection={<IconDownload size={16} />} loading={downloading} onClick={download}>
              Скачать Excel
            </Button>
          </Group>
        </Group>
      </Paper>

      <Tabs defaultValue="summary" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="summary">Свод ({doc.summary.length})</Tabs.Tab>
          <Tabs.Tab value="detail">По помещениям ({doc.items.length})</Tabs.Tab>
          <Tabs.Tab value="check">Проверка ({stats.warnings})</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="summary" pt="md">
          <SummaryTable rows={doc.summary} />
        </Tabs.Panel>
        <Tabs.Panel value="detail" pt="md">
          <DetailTable rows={doc.items} />
        </Tabs.Panel>
        <Tabs.Panel value="check" pt="md">
          <CheckTable doc={doc} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
