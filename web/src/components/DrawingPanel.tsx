import { Alert, Button, Checkbox, FileInput, Group, Pagination, Stack, Table, Text, TextInput } from '@mantine/core'
import { useMemo, useState } from 'react'
import { uploadSource, checkDrawing, type DrawingCheckResult } from '../api'
import { useWorkspace } from '../store'

const STATUS: Record<string, string> = {
  match: 'Число меток совпало', difference: 'Количество отличается — проверить', not_found: 'Метки не найдены',
  ambiguous: 'Номер повторяется в списке — сверить вручную', no_position: 'Без номера позиции',
  not_checked: 'Страницы не прочитаны', quantity_not_comparable: 'Единица не шт. — количество не сравниваем', no_quantity: 'В списке нет количества',
}

export function DrawingPanel() {
  const documents = useWorkspace((s) => s.documents)
  const [file, setFile] = useState<File | null>(null)
  const [pages, setPages] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<DrawingCheckResult | null>(null)
  const [checkedItems, setCheckedItems] = useState('')
  const [onlyIssues, setOnlyIssues] = useState(true)
  const [page, setPage] = useState(1)
  const items = useMemo(() => documents.flatMap((d) => d.doc.summary.filter((r) => !r.excluded)), [documents])
  const signature = JSON.stringify(items.map(({ pos, name, qty, unit }) => ({ pos, name, qty, unit })))
  const rows = result?.rows.filter((r) => !onlyIssues || r.status !== 'match') ?? []
  async function choosePlan(value: File | null) {
    setFile(null); resetResult()
    if (!value) return
    if (value.size > 25 * 1024 ** 2) { setError('Для сверки нужен PDF до 25 МБ.'); return }
    setBusy(true)
    try {
      const workspace = useWorkspace.getState()
      await uploadSource(value, workspace.projectId, workspace.title)
      setFile(value)
    } catch (e) { setError(`Не удалось сохранить план: ${e instanceof Error ? e.message : String(e)}`) }
    finally { setBusy(false) }
  }
  async function run() {
    if (!file) return
    if (file.size > 25 * 1024 ** 2) { setError('Для сверки нужен PDF до 25 МБ. Выделите нужные планы в отдельный файл.'); return }
    setBusy(true); setError(''); setResult(null)
    try { setResult(await checkDrawing(file, pages, items)); setCheckedItems(signature); setPage(1) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  function resetResult() { setResult(null); setError(''); setPage(1) }
  return <Stack gap="md">
    <Alert color="blue" title="Сверка текстовых меток на плане">
      Выберите PDF до 25 МБ и номера страниц именно с планами. Считаются отдельные подписи «2.10», «Поз. 2.10», «2.10 = 6».
      Одна подпись считается одной единицей, если количество не указано. Сканы, символы оборудования и помещения не распознаются.
    </Alert>
    <Group align="flex-end">
      <FileInput label="PDF с планом" accept=".pdf" value={file} clearable disabled={busy} style={{ flex: 1 }} onChange={(v) => void choosePlan(v)} />
      <TextInput label="Страницы плана" placeholder="1, 2, 3 — максимум 20" value={pages} disabled={busy} onChange={(e) => { setPages(e.currentTarget.value); resetResult() }} />
      <Button loading={busy} disabled={!file || !pages.trim() || items.length === 0} onClick={run}>Сверить со списком товаров</Button>
    </Group>
    {file && <Text size="xs" c="dimmed">Оригинал плана сохранён в разделе «Документы».</Text>}
    {error && <Alert color="red">{error}</Alert>}
    {result && <>
      <Alert color="yellow">{result.warnings.map((w, i) => <Text size="sm" key={i}>{w}</Text>)}</Alert>
      {checkedItems !== signature && <Alert color="orange">Список товаров изменился после сверки. Запустите её повторно.</Alert>}
      <Group justify="space-between">
        <Text size="sm">Проверено позиций: {result.rows.length}. Совпадений числа меток: {result.rows.filter((r) => r.status === 'match').length}.</Text>
        <Checkbox label="Показать только замечания" checked={onlyIssues} onChange={(e) => { setOnlyIssues(e.currentTarget.checked); setPage(1) }} />
      </Group>
      <Table.ScrollContainer minWidth={850}>
        <Table striped withTableBorder><Table.Thead><Table.Tr>
          {['Позиция', 'Товар', 'В списке', 'Метки на плане', 'Результат', 'Где найдены'].map((h) => <Table.Th key={h}>{h}</Table.Th>)}
        </Table.Tr></Table.Thead><Table.Tbody>
          {rows.slice((page - 1) * 50, page * 50).map((r, i) => <Table.Tr key={i}>
            <Table.Td>{r.pos || '—'}</Table.Td><Table.Td>{r.name}</Table.Td><Table.Td>{r.expected ?? '—'} {r.unit}</Table.Td>
            <Table.Td>{r.found}</Table.Td><Table.Td>{STATUS[r.status] ?? r.status}</Table.Td>
            <Table.Td>{r.hits.slice(0, 10).map((h, j) => <Text size="xs" key={j}>Стр. {h.page}: {h.text} (x={h.x}, y={h.y})</Text>)}{r.hits.length > 10 && <Text size="xs">Ещё {r.hits.length - 10} меток</Text>}</Table.Td>
          </Table.Tr>)}
        </Table.Tbody></Table>
      </Table.ScrollContainer>
      {rows.length === 0 && <Text>Нет замечаний по выбранному фильтру.</Text>}
      <Pagination total={Math.max(1, Math.ceil(rows.length / 50))} value={page} onChange={setPage} />
      {result.unknown_labels.length > 0 && <Alert color="gray" title="Числовые подписи вне списка — могут быть размерами или номерами помещений">
        {result.unknown_labels.slice(0, 100).join('; ')}{result.unknown_labels.length > 100 && `; ещё ${result.unknown_labels.length - 100}`}
      </Alert>}
    </>}
  </Stack>
}
