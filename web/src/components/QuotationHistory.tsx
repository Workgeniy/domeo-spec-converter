import { Alert, Button, Group, Loader, Paper, Stack, Switch, Text, TextInput } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useEffect, useState } from 'react'
import { downloadBlob } from '../export'
import { downloadQuotation, getQuotation, listQuotations, openQuotation, type QuotationInfo } from '../quotations'
import { useWorkspace } from '../store'

export function QuotationHistory({ onOpened }: { onOpened: () => void }) {
  const projectId = useWorkspace((s) => s.projectId)
  const hasDocuments = useWorkspace((s) => s.documents.length > 0)
  const [currentOnly, setCurrentOnly] = useState(false)
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [rows, setRows] = useState<QuotationInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    setLoading(true); setError('')
    const timer = window.setTimeout(() => {
      listQuotations(search, offset, currentOnly ? projectId : undefined)
        .then((data) => { if (!cancelled) setRows(data) })
        .catch((e) => { if (!cancelled) setError(String(e.message || e)) })
        .finally(() => { if (!cancelled) setLoading(false) })
    }, 250)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [search, offset, reload, currentOnly, projectId])
  async function act(row: QuotationInfo, open: boolean) {
    if (open && !window.confirm('Вернуть рабочий объект к этой версии КП? Его текущие данные будут заменены данными выбранной версии. Все сформированные Excel останутся в истории.')) return
    setBusy(row.id)
    try {
      if (open) { await openQuotation(await getQuotation(row.id)); onOpened() }
      else downloadBlob(await downloadQuotation(row), row.file_name)
    } catch (e) { notifications.show({ color: 'red', title: 'История КП', message: e instanceof Error ? e.message : String(e) }) }
    finally { setBusy(null) }
  }
  return <Stack>
    <Text size="sm" c="dimmed">Каждое сформированное КП сохраняется отдельной версией. Можно скачать прежний Excel или открыть данные, изменить цены и сформировать новую версию.</Text>
    <Group>
      <TextInput style={{ flex: 1 }} placeholder="Поиск по объекту или номеру договора" maxLength={200} value={search}
        onChange={(e) => { setSearch(e.currentTarget.value); setOffset(0) }} />
      <Button variant="default" onClick={() => setReload((v) => v + 1)} disabled={loading}>Обновить</Button>
    </Group>
    {hasDocuments && <Switch label="Только текущий объект" checked={currentOnly}
      onChange={(e) => { setCurrentOnly(e.currentTarget.checked); setOffset(0) }} />}
    {loading ? <Loader size="sm" /> : error ? <Alert color="red">{error}</Alert> : <>
      {rows.length === 0 && <Text c="dimmed">Сохранённых КП пока нет.</Text>}
      {rows.slice(0, 30).map((row) => <Paper key={row.id} withBorder p="md">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Stack gap={4} style={{ flex: 1, minWidth: 240 }}>
            <Text fw={600}>{row.title || 'Без названия'}</Text>
            <Text size="sm">{new Date(row.created_at).toLocaleString('ru-RU')} · {row.positions} поз. · {row.margin_percent == null ? 'Расчёт по наценке' : `Маржа ${row.margin_percent}%`}</Text>
            <Text size="xs" c="dimmed">Договор: {row.contract_number || 'не указан'} · {row.template_name}</Text>
            <Text size="xs" c="dimmed">Версия {row.id.slice(0, 8)}{row.parent_id ? ` · на основе ${row.parent_id.slice(0, 8)}` : ''}</Text>
          </Stack>
          <Group gap="xs">
            <Button variant="light" disabled={busy !== null} loading={busy === row.id} onClick={() => act(row, false)}>Скачать Excel</Button>
            <Button disabled={busy !== null} onClick={() => act(row, true)}>Открыть и редактировать</Button>
          </Group>
        </Group>
      </Paper>)}
      <Group justify="space-between">
        <Button variant="subtle" disabled={offset === 0} onClick={() => setOffset((n) => Math.max(0, n - 30))}>Назад</Button>
        <Text size="sm">Страница {Math.floor(offset / 30) + 1}</Text>
        <Button variant="subtle" disabled={rows.length <= 30} onClick={() => setOffset((n) => n + 30)}>Далее</Button>
      </Group>
    </>}
  </Stack>
}
