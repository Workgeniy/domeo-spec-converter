import { Alert, Badge, Button, Group, Loader, Paper, Stack, Text, TextInput } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useEffect, useState } from 'react'
import { downloadUpload, listUploads, parseUpload, type UploadInfo } from '../api'
import { downloadBlob } from '../export'
import { openUpload } from '../uploads'

export function UploadedDocuments({ onOpened }: { onOpened: () => void }) {
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [rows, setRows] = useState<UploadInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    setLoading(true); setError('')
    const timer = window.setTimeout(() => {
      listUploads(search, offset).then((data) => { if (!cancelled) setRows(data) })
        .catch((e) => { if (!cancelled) setError(e.message || String(e)) })
        .finally(() => { if (!cancelled) setLoading(false) })
    }, 250)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [search, offset, reload])
  async function act(row: UploadInfo, open: boolean) {
    setBusy(row.id)
    try {
      if (open) { await openUpload(await parseUpload(row.id)); onOpened() }
      else downloadBlob(await downloadUpload(row.id), row.file_name)
    } catch (e) {
      notifications.show({ color: 'red', title: 'Документы', message: e instanceof Error ? e.message : String(e), autoClose: false })
      setReload((n) => n + 1)
    } finally { setBusy(null) }
  }
  return <Stack>
    <Text size="sm" c="dimmed">Общий архив загруженных PDF и Excel. Оригиналы сохраняются сразу, до разбора и формирования КП. Открытие исходника создаёт новый рабочий объект. Продолжить работу с правками и ценами можно в разделе «Объекты».</Text>
    <Group>
      <TextInput style={{ flex: 1 }} placeholder="Поиск по имени файла или объекту" maxLength={200} value={search}
        onChange={(e) => { setSearch(e.currentTarget.value); setOffset(0) }} />
      <Button variant="default" disabled={loading} onClick={() => setReload((n) => n + 1)}>Обновить</Button>
    </Group>
    {loading ? <Loader size="sm" /> : error ? <Alert color="red">{error}</Alert> : <>
      {!rows.length && <Text c="dimmed">Загруженных документов пока нет.</Text>}
      {rows.slice(0, 30).map((row) => <Paper withBorder p="md" key={row.id}>
        <Group justify="space-between" align="flex-start">
          <Stack gap={4} style={{ flex: 1, minWidth: 200 }}>
            <Text fw={600}>{row.file_name}</Text>
            {row.title && <Text size="sm">{row.title}</Text>}
            <Text size="xs" c="dimmed">{new Date(row.created_at).toLocaleString('ru-RU')} · {(row.size / 1024 / 1024).toFixed(2)} МБ</Text>
            <Badge variant="light" color={row.parsed ? 'green' : row.error ? 'orange' : 'blue'}>{row.parsed ? 'Разобран' : row.error ? 'Ошибка разбора — оригинал сохранён' : 'Оригинал сохранён'}</Badge>
            {row.error && <Text size="xs" c="orange">{row.error}</Text>}
          </Stack>
          <Group gap="xs">
            <Button variant="light" disabled={busy !== null} onClick={() => act(row, false)}>Скачать оригинал</Button>
            <Button loading={busy === row.id} disabled={busy !== null} onClick={() => act(row, true)}>{row.parsed ? 'Создать объект' : 'Разобрать и создать объект'}</Button>
          </Group>
        </Group>
      </Paper>)}
      <Group justify="space-between">
        <Button variant="subtle" disabled={!offset} onClick={() => setOffset((n) => Math.max(0, n - 30))}>Назад</Button>
        <Text size="sm">Страница {Math.floor(offset / 30) + 1}</Text>
        <Button variant="subtle" disabled={rows.length <= 30} onClick={() => setOffset((n) => n + 30)}>Далее</Button>
      </Group>
    </>}
  </Stack>
}
