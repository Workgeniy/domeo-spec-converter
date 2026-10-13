import { Alert, Button, Group, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { retryProject, reloadProject, saveProjectCopy, useCloud } from '../projects'
import { useLocalPersistence, useWorkspace } from '../store'

export function CloudStatus() {
  const { status, error, busy } = useCloud()
  const updatedAt = useWorkspace((s) => s.cloud.updatedAt)
  const localFailed = useLocalPersistence((s) => s.failed)
  const run = async (action: () => Promise<void>) => {
    try { await action() } catch (e) { notifications.show({ color: 'red', title: 'Сохранение объекта', message: e instanceof Error ? e.message : String(e) }) }
  }
  if (status === 'idle') return null
  if (status === 'conflict' || status === 'error') return <Alert color={status === 'conflict' ? 'orange' : 'red'} mb="md"
    title={status === 'conflict' ? 'Объект изменён в другом окне' : 'Не удалось сохранить или загрузить объект'}>
    <Text size="sm">{error}</Text>
    <Text size="sm" mt={4}>До успешного сохранения оставьте эту вкладку открытой. Правки в ней доступны для сохранения отдельной копией.</Text>
    <Group mt="sm">
      {status !== 'conflict' && <Button size="xs" disabled={busy} onClick={() => run(retryProject)}>Повторить</Button>}
      <Button size="xs" variant="light" disabled={busy} onClick={() => run(saveProjectCopy)}>Сохранить отдельной копией</Button>
      {status === 'conflict' && <Button size="xs" variant="default" disabled={busy} onClick={() => run(reloadProject)}>Открыть сохранённый объект</Button>}
    </Group>
  </Alert>
  return <><Text size="sm" c={status === 'saved' ? 'teal' : 'dimmed'} mb="sm" role="status">
    {status === 'saved' ? `Все изменения сохранены · ${new Date(updatedAt).toLocaleTimeString('ru-RU')}` :
      status === 'saving' ? 'Сохранение…' : 'Есть изменения — ожидают сохранения…'}
  </Text>{localFailed && status !== 'saved' && <Alert color="orange" mb="md">В браузере не хватает места для резервной копии. Не закрывайте вкладку до появления «Все изменения сохранены».</Alert>}</>
}
