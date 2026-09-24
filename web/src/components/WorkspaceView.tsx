import { ActionIcon, Badge, Button, Collapse, Group, Menu, Paper, Stack, Tabs, Text, TextInput, Tooltip } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconChevronDown, IconDownload, IconPlus, IconTrash, IconX } from '@tabler/icons-react'
import { useMemo, useState } from 'react'

import { exportExcel } from '../api'
import { buildExportRequest, downloadBlob } from '../export'
import { kpTotals } from '../kp'
import { useWorkspace, type WorkspaceDocument } from '../store'
import { CheckTable } from './CheckTable'
import { DetailTable } from './DetailTable'
import { formatMoney } from './format'
import { KpPanel } from './KpPanel'
import { SummaryTable } from './SummaryTable'
import { UploadPane } from './UploadPane'

export function WorkspaceView() {
  const { title, documents, kp, setTitle, addDocument, removeDocument, clear } = useWorkspace()
  const [adding, setAdding] = useState(false)
  const [downloading, setDownloading] = useState(false)

  const stats = useMemo(() => {
    const items = documents.reduce((n, d) => n + d.doc.items.length, 0)
    const rows = documents.flatMap((d) => d.doc.summary)
    const active = rows.filter((r) => !r.excluded)
    const totals = kpTotals(active, kp)
    const warnings = documents.reduce(
      (n, d) =>
        n +
        d.doc.warnings.length +
        d.doc.pages.reduce((m, p) => m + p.warnings.length, 0) +
        d.doc.items.reduce((m, i) => m + i.warnings.length, 0) +
        d.doc.summary.reduce((m, s) => m + s.warnings.length, 0),
      0,
    )
    return { items, positions: active.length, excluded: rows.length - active.length, priced: totals.priced, total: totals.total, warnings }
  }, [documents, kp])

  // withKp: приложения к договору по образцу (листы «1» и «2»); иначе рабочая выгрузка
  // (свод, по помещениям, проверка) — для себя, не для заказчика.
  async function download(docs: WorkspaceDocument[], withKp = true) {
    setDownloading(true)
    try {
      const { blob, fileName } = await exportExcel(buildExportRequest(title, docs, withKp ? kp : null))
      downloadBlob(blob, fileName)
    } catch (e) {
      notifications.show({ color: 'red', title: 'Не удалось сформировать Excel', message: e instanceof Error ? e.message : String(e) })
    } finally {
      setDownloading(false)
    }
  }

  function reset() {
    if (window.confirm('Закрыть объект? Загруженные документы и правки будут удалены из браузера.')) clear()
  }

  return (
    <Stack gap="md">
      <Paper withBorder p="md">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Stack gap={6} style={{ flex: 1, minWidth: 320 }}>
            <TextInput
              variant="unstyled"
              size="lg"
              fw={700}
              placeholder="Название объекта"
              value={title}
              onChange={(e) => setTitle(e.currentTarget.value)}
              styles={{ input: { fontWeight: 700 } }}
            />
            <Group gap={6} wrap="wrap">
              {documents.map((d) => (
                <Badge
                  key={d.id}
                  size="lg"
                  variant="light"
                  rightSection={
                    <Tooltip label="Убрать документ">
                      <ActionIcon size="xs" variant="transparent" color="gray" onClick={() => removeDocument(d.id)} aria-label="убрать">
                        <IconX size={12} />
                      </ActionIcon>
                    </Tooltip>
                  }
                >
                  {d.doc.doc_code || d.doc.file_name} · {d.doc.items.length} строк · {d.doc.summary.length} поз.
                </Badge>
              ))}
              <Button size="compact-sm" variant="subtle" leftSection={<IconPlus size={14} />} onClick={() => setAdding((v) => !v)}>
                {adding ? 'Скрыть' : 'Добавить том'}
              </Button>
            </Group>
            <Group gap="xs">
              <Badge variant="outline" color="gray">
                строк из PDF: {stats.items}
              </Badge>
              <Badge variant="outline" color="gray">
                позиций в КП: {stats.positions}
                {stats.excluded > 0 && ` (исключено ${stats.excluded})`}
              </Badge>
              <Badge variant="outline" color={stats.priced === stats.positions ? 'green' : 'gray'}>
                с ценой: {stats.priced} из {stats.positions}
              </Badge>
              <Badge variant="outline" color={stats.warnings ? 'yellow' : 'green'}>
                замечаний: {stats.warnings}
              </Badge>
              <Badge variant="filled" color={stats.total > 0 ? 'blue' : 'gray'}>
                итого по КП: {formatMoney(stats.total)} ₽
              </Badge>
            </Group>
          </Stack>
          <Group>
            <Button variant="default" color="red" leftSection={<IconTrash size={16} />} onClick={reset}>
              Закрыть объект
            </Button>
            <Menu shadow="md" width={360}>
              <Menu.Target>
                <Button leftSection={<IconDownload size={16} />} rightSection={<IconChevronDown size={14} />} loading={downloading}>
                  Сформировать КП (Excel)
                </Button>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Item onClick={() => download(documents)} fw={600}>
                  {documents.length > 1 ? 'КП по объекту целиком (все тома)' : 'КП — приложения №1.1 и №1.2'}
                </Menu.Item>
                {documents.length > 1 && (
                  <>
                    <Menu.Label>КП только по одному тому</Menu.Label>
                    {documents.map((d) => (
                      <Menu.Item key={d.id} onClick={() => download([d])}>
                        {d.doc.doc_code || d.doc.file_name}
                      </Menu.Item>
                    ))}
                  </>
                )}
                <Menu.Divider />
                <Menu.Item onClick={() => download(documents, false)}>Рабочая выгрузка (свод, по помещениям, проверка)</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
        <Collapse expanded={adding}>
          <div style={{ marginTop: 12 }}>
            <UploadPane
              compact
              onParsed={(doc) => {
                addDocument(doc)
                setAdding(false)
              }}
            />
          </div>
        </Collapse>
      </Paper>

      <Tabs defaultValue="summary" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="summary">Свод для КП ({stats.positions})</Tabs.Tab>
          <Tabs.Tab value="kp" fw={600}>
            Формирование КП
          </Tabs.Tab>
          <Tabs.Tab value="detail">По помещениям ({stats.items})</Tabs.Tab>
          <Tabs.Tab value="check">Проверка ({stats.warnings})</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="summary" pt="md">
          <SummaryTable />
        </Tabs.Panel>
        <Tabs.Panel value="kp" pt="md">
          <KpPanel onDownload={() => download(documents)} downloading={downloading} />
        </Tabs.Panel>
        <Tabs.Panel value="detail" pt="md">
          <DetailTable />
        </Tabs.Panel>
        <Tabs.Panel value="check" pt="md">
          <CheckTable />
        </Tabs.Panel>
      </Tabs>
      <Text size="xs" c="dimmed">
        Свод: одна строка на позицию, количество сложено по всем помещениям. Раздел, наименование, характеристики, единица, количество и цена
        редактируются прямо в таблице; исключённые строки в Excel не попадают.
      </Text>
    </Stack>
  )
}
