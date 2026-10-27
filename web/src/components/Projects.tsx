import { Alert, Button, Group, Loader, Paper, Stack, Text, TextInput, Title } from '@mantine/core'
import { useEffect, useState } from 'react'
import { listProjects, type ProjectInfo } from '../api'
import { closeProject, openProject } from '../projects'

export function Projects({ onOpened }: { onOpened: () => void }) {
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [rows, setRows] = useState<ProjectInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    const timer = setTimeout(() => {
      listProjects(search, offset).then((data) => { if (!cancelled) { setRows(data); setError('') } })
        .catch((e) => { if (!cancelled) setError(e.message || String(e)) })
        .finally(() => { if (!cancelled) setLoading(false) })
    }, 250)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [search, offset, reload])
  async function open(id?: string) {
    setBusy(true); setError('')
    try { if (id) await openProject(id); else await closeProject(); onOpened() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  return <Stack>
    <Group justify="space-between"><Title order={3}>Объекты</Title><Button disabled={busy} onClick={() => open()}>Новый объект</Button></Group>
    <Text size="sm" c="dimmed">Общий список для пользователей этого сервера. Товары, цены, маржа и форма КП сохраняются автоматически. Откройте объект, чтобы продолжить работу.</Text>
    <Group>
      <TextInput style={{ flex: 1 }} placeholder="Поиск по названию объекта" maxLength={200} value={search}
        onChange={(e) => { setSearch(e.currentTarget.value); setOffset(0) }} />
      <Button variant="default" disabled={loading} onClick={() => setReload((n) => n + 1)}>Обновить</Button>
    </Group>
    {error && <Alert color="red">{error}</Alert>}
    {loading ? <Loader size="sm" /> : <>
      {!rows.length && !error && <Text c="dimmed">Пока нет объектов. Загрузите спецификацию выше — объект появится после разбора.</Text>}
      {rows.slice(0, 30).map((row) => <Paper withBorder p="md" key={row.id}>
        <Group justify="space-between" align="flex-start">
          <Stack gap={3} style={{ flex: 1, minWidth: 200 }}>
            <Text fw={600}>{row.title || 'Без названия'}</Text>
            <Text size="sm">{row.documents} томов · {row.positions} позиций · {row.margin_percent == null ? 'Расчёт по наценке' : `Маржа ${row.margin_percent}%`}</Text>
            <Text size="xs" c="dimmed">Изменён {new Date(row.updated_at).toLocaleString('ru-RU')} · {row.quotation_id ? 'Есть сформированное КП' : 'Рабочий черновик'}</Text>
          </Stack>
          <Button disabled={busy} onClick={() => open(row.id)}>Продолжить работу</Button>
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
