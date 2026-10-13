import { ActionIcon, Badge, Button, Collapse, Group, Menu, Paper, Stack, Tabs, Text, TextInput, Tooltip } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconChevronDown, IconDownload, IconPlus, IconX } from '@tabler/icons-react'
import { useMemo, useRef, useState } from 'react'

import { exportExcel, type ExportKind } from '../api'
import { crossVolumeDuplicates } from '../duplicates'
import { buildExportRequest, downloadBlob } from '../export'
import { kpTotals } from '../kp'
import { saveQuotation, downloadQuotation } from '../quotations'
import { useWorkspace, type WorkspaceDocument } from '../store'
import { closeProject, flushProject } from '../projects'
import { CheckTable } from './CheckTable'
import { CostPanel } from './CostPanel'
import { DetailTable } from './DetailTable'
import { DrawingPanel } from './DrawingPanel'
import { formatMoney } from './format'
import { KpPanel } from './KpPanel'
import { SummaryTable } from './SummaryTable'
import { UploadPane } from './UploadPane'

export function WorkspaceView() {
  const { title, documents, kp, indexation, setTitle, addDocument, removeDocument } = useWorkspace()
  const saving = useRef(false)
  const quotationId = useWorkspace((s) => s.quotationId)
  const [adding, setAdding] = useState(false)
  const [downloading, setDownloading] = useState(false)

  const stats = useMemo(() => {
    const items = documents.reduce((n, d) => n + d.doc.items.length, 0)
    const rows = documents.flatMap((d) => d.doc.summary)
    const active = rows.filter((r) => !r.excluded)
    const totals = kpTotals(active, kp, indexation)
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
  }, [documents, kp, indexation])

  const duplicateGroups = useMemo(() => crossVolumeDuplicates(documents).length, [documents])

  // kp — приложения к договору по образцу (листы «1» и «2»); cost — себестоимость для Домео;
  // working — рабочая выгрузка (свод, по помещениям, проверка).
  async function download(docs: WorkspaceDocument[], kind: ExportKind = 'kp') {
    if (saving.current) return
    saving.current = true
    setDownloading(true)
    try {
      if (kind === 'kp') {
        const saved = await saveQuotation(docs)
        notifications.show({ color: 'green', title: 'КП сохранено в истории', message: 'Эту версию можно открыть или скачать позднее.' })
        // Excel уже сохранён в истории. Ошибка обновления рабочего объекта видна в CloudStatus.
        await flushProject().catch(() => {})
        downloadBlob(await downloadQuotation(saved), saved.file_name)
      } else {
        const { blob, fileName } = await exportExcel(buildExportRequest(title, docs, kp, kind, indexation))
        downloadBlob(blob, fileName)
      }
    } catch (e) {
      notifications.show({ color: 'red', title: 'Не удалось сформировать Excel', message: e instanceof Error ? e.message : String(e) })
    } finally {
      saving.current = false
      setDownloading(false)
    }
  }

  async function reset() {
    try { await closeProject() }
    catch (e) { notifications.show({ color: 'red', title: 'Объект остаётся открыт', message: e instanceof Error ? e.message : String(e) }) }
  }

  return (
    <Stack gap="md">
      <Paper withBorder p="md">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Stack gap={6} style={{ flex: 1, minWidth: 320 }}>
            {quotationId && <Text size="xs" c="dimmed">Версия в истории: {quotationId.slice(0, 8)}. Рабочие правки сохраняются автоматически. Этот Excel в истории не меняется.</Text>}
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
                строк из файла: {stats.items}
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
            <Button variant="default" onClick={reset}>
              Закрыть объект
            </Button>
            <Menu shadow="md" width={360}>
              <Menu.Target>
                <Button leftSection={<IconDownload size={16} />} rightSection={<IconChevronDown size={14} />} loading={downloading} disabled={!documents.length}>
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
                <Menu.Item onClick={() => download(documents, 'cost')}>Себестоимость для Домео (три цены, выбор)</Menu.Item>
                <Menu.Item onClick={() => download(documents, 'working')}>Рабочая выгрузка (свод, по помещениям, проверка)</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
        <Collapse expanded={adding}>
          <div style={{ marginTop: 12 }}>
            <UploadPane
              compact
              onParsed={(doc, original) => {
                addDocument(doc, original)
                setAdding(false)
              }}
            />
          </div>
        </Collapse>
      </Paper>

      <Tabs defaultValue="summary" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="summary">Свод для КП ({stats.positions})</Tabs.Tab>
          <Tabs.Tab value="cost">Себестоимость</Tabs.Tab>
          <Tabs.Tab value="kp" fw={600}>
            Формирование КП
          </Tabs.Tab>
          <Tabs.Tab value="detail">По помещениям ({stats.items})</Tabs.Tab>
          <Tabs.Tab value="drawing">Сверка с планом</Tabs.Tab>
          <Tabs.Tab value="check" rightSection={duplicateGroups > 0 ? <Badge size="xs" color="orange" circle>{duplicateGroups}</Badge> : undefined}>
            Проверка ({stats.warnings})
          </Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="summary" pt="md">
          <SummaryTable />
        </Tabs.Panel>
        <Tabs.Panel value="cost" pt="md">
          <CostPanel onDownload={() => download(documents, 'cost')} downloading={downloading} />
        </Tabs.Panel>
        <Tabs.Panel value="kp" pt="md">
          <KpPanel onDownload={() => download(documents, 'kp')} downloading={downloading} />
        </Tabs.Panel>
        <Tabs.Panel value="detail" pt="md">
          <DetailTable />
        </Tabs.Panel>
        <Tabs.Panel value="drawing" pt="md">
          <DrawingPanel />
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
