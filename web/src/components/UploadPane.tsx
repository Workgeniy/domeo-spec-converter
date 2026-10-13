import { Alert, Group, List, Progress, Stack, Text, rem } from '@mantine/core'
import { Dropzone, MIME_TYPES, PDF_MIME_TYPE } from '@mantine/dropzone'
import { IconFileImport, IconInfoCircle, IconUpload, IconX } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { notifications } from '@mantine/notifications'
import type { OriginalFile } from '../originals'
import { uploadedOriginal } from '../uploads'
import { useWorkspace } from '../store'
import { useTemplates } from '../templates'

import { getHealth, uploadSource, parseUpload, type ParsedDocument } from '../api'

// Том спецификации принимаем и PDF, и Excel — таблица от проектировщика бывает сразу в xlsx.
const XLSM_MIME = 'application/vnd.ms-excel.sheet.macroEnabled.12'
const ACCEPT = [...PDF_MIME_TYPE, MIME_TYPES.xlsx, XLSM_MIME]

interface Props {
  onParsed: (doc: ParsedDocument, original?: OriginalFile) => void
  /** Компактный вид — для добавления томов к уже открытому объекту. */
  compact?: boolean
}

interface Progress {
  done: number
  total: number
  current: string
}

export function UploadPane({ onParsed, compact = false }: Props) {
  const [progress, setProgress] = useState<Progress | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  // undefined — ещё не спросили; null — ядро недоступно или OCR не установлен
  const [ocr, setOcr] = useState<string | null | undefined>(undefined)
  const [engineDown, setEngineDown] = useState(false)

  useEffect(() => {
    getHealth()
      .then((h) => {
        setEngineDown(!h.engine.available)
        setOcr(h.engine.ocr)
      })
      .catch(() => {
        setEngineDown(true)
        setOcr(null)
      })
  }, [])

  // Тома одного объекта разбираются по очереди: ядро и так занимает всё ядро процессора
  // на один документ, а очередь даёт понятный прогресс. В рабочее пространство документы
  // отдаются разом в конце: иначе после первого тома эта панель исчезнет вместе с прогрессом.
  async function handleDrop(files: File[]) {
    setErrors([])
    const state = useWorkspace.getState()
    const failed: string[] = []
    const parsed: { doc: ParsedDocument; original?: OriginalFile }[] = []
    for (const [i, file] of files.entries()) {
      setProgress({ done: i, total: files.length, current: file.name })
      try {
        const saved = await uploadSource(file, state.projectId, state.title)
        let doc: ParsedDocument
        try {
          const result = await parseUpload(saved.id)
          if (!result.document) throw new Error('Нет результата разбора.')
          doc = result.document
        } catch (e) {
          throw new Error(`Оригинал сохранён в «Документы». Разбор не завершён: ${e instanceof Error ? e.message : String(e)}`)
        }
        const original = await uploadedOriginal(saved, doc, false, file)
        parsed.push({ doc, original })
      } catch (e) {
        failed.push(`${file.name}: ${e instanceof Error ? e.message : String(e)}`)
      }
    }
    setProgress(null)
    setErrors(failed)
    if (failed.length && parsed.length) notifications.show({ color: 'orange', title: 'Не все файлы разобраны', message: failed.join('\n'), autoClose: false })
    if (useWorkspace.getState().projectId === state.projectId) {
      const templateId = parsed.find((d) => d.original?.templateId)?.original?.templateId
      if (!compact && templateId) useTemplates.getState().select(templateId)
      parsed.forEach(({ doc, original }) => onParsed(doc, original))
    }
    else notifications.show({ title: 'Файлы сохранены', message: 'Найти загруженные файлы можно в разделе «Документы».' })
  }

  const busy = progress !== null

  return (
    <Stack gap="md" maw={compact ? undefined : 820} mx={compact ? undefined : 'auto'} mt={compact ? undefined : 'xl'}>
      <Dropzone onDrop={handleDrop} accept={ACCEPT} maxSize={100 * 1024 ** 2} multiple loading={busy}>
        <Group justify="center" gap="xl" mih={compact ? 80 : 200} style={{ pointerEvents: 'none' }}>
          <Dropzone.Accept>
            <IconUpload style={{ width: rem(compact ? 32 : 52), height: rem(compact ? 32 : 52) }} stroke={1.5} />
          </Dropzone.Accept>
          <Dropzone.Reject>
            <IconX style={{ width: rem(compact ? 32 : 52), height: rem(compact ? 32 : 52) }} stroke={1.5} />
          </Dropzone.Reject>
          <Dropzone.Idle>
            <IconFileImport style={{ width: rem(compact ? 32 : 52), height: rem(compact ? 32 : 52) }} stroke={1.5} />
          </Dropzone.Idle>
          <div>
            <Text size={compact ? 'md' : 'xl'} inline>
              {compact
                ? 'Добавить ещё том этого объекта (PDF или Excel)'
                : 'Перетащите тома «Технологические решения» — PDF или Excel — или нажмите для выбора'}
            </Text>
            <Text size="sm" c="dimmed" inline mt={7}>
              {compact
                ? 'Например, ТХ2 (пищеблок) к уже загруженному ТХ1'
                : 'Можно несколько файлов сразу — ТХ1 и ТХ2 одного объекта попадут в одну спецификацию. PDF или xlsx, до 100 МБ каждый.'}
            </Text>
          </div>
        </Group>
      </Dropzone>

      <Text size="xs" c="dimmed">Оригиналы PDF и Excel автоматически сохраняются в общей базе до разбора, даже без формирования КП. Найти их можно в разделе «Документы».</Text>

      {progress && (
        <Stack gap={4}>
          <Text size="sm">
            Сохраняем и разбираем {progress.current}
            {progress.total > 1 && ` (${progress.done + 1} из ${progress.total})`}…
          </Text>
          <Progress value={progress.total > 1 ? (progress.done / progress.total) * 100 : 100} animated />
        </Stack>
      )}

      {engineDown && (
        <Alert color="orange" title="Ядро разбора не отвечает" icon={<IconX size={18} />}>
          Исходный файл сохранится в базе. Разбор можно будет повторить из раздела «Документы», когда Python-сервис станет доступен.
        </Alert>
      )}

      {errors.length > 0 && (
        <Alert color="red" title="Не получилось" icon={<IconX size={18} />}>
          <List size="sm">
            {errors.map((e) => (
              <List.Item key={e}>{e}</List.Item>
            ))}
          </List>
        </Alert>
      )}

      {!compact && (
        <Alert variant="light" color="gray" icon={<IconInfoCircle size={18} />} title="Что делает сервис">
          <List size="sm" spacing={4}>
            <List.Item>Находит листы «Спецификация технологического оборудования» и читает таблицу — в PDF или в Excel.</List.Item>
            <List.Item>Столбцы определяет по словам шапки («Поз.», «Наименование», «Кол-во»…), поэтому их порядок в файле любой.</List.Item>
            <List.Item>Сводит одинаковые позиции из разных помещений и считает общее количество.</List.Item>
            <List.Item>Даёт поправить свод, проставить разделы и цены, исключить лишнее — и выгружает Excel по форме КП.</List.Item>
            <List.Item>
              Сканы PDF без текстового слоя распознаются через OCR:{' '}
              {ocr === undefined ? '…' : ocr ? `доступен (${ocr})` : 'на сервере не установлен, такие страницы будут пропущены'}
              .
            </List.Item>
          </List>
        </Alert>
      )}
    </Stack>
  )
}
