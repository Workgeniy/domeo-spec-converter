import { Alert, Group, List, Progress, Stack, Text, rem } from '@mantine/core'
import { Dropzone, PDF_MIME_TYPE } from '@mantine/dropzone'
import { IconFileTypePdf, IconInfoCircle, IconUpload, IconX } from '@tabler/icons-react'
import { useEffect, useState } from 'react'

import { getHealth, parsePdf, type ParsedDocument } from '../api'

interface Props {
  onParsed: (doc: ParsedDocument) => void
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
    const failed: string[] = []
    const parsed: ParsedDocument[] = []
    for (const [i, file] of files.entries()) {
      setProgress({ done: i, total: files.length, current: file.name })
      try {
        parsed.push(await parsePdf(file))
      } catch (e) {
        failed.push(`${file.name}: ${e instanceof Error ? e.message : String(e)}`)
      }
    }
    setProgress(null)
    setErrors(failed)
    parsed.forEach(onParsed)
  }

  const busy = progress !== null

  return (
    <Stack gap="md" maw={compact ? undefined : 820} mx={compact ? undefined : 'auto'} mt={compact ? undefined : 'xl'}>
      <Dropzone onDrop={handleDrop} accept={PDF_MIME_TYPE} maxSize={100 * 1024 ** 2} multiple loading={busy}>
        <Group justify="center" gap="xl" mih={compact ? 80 : 200} style={{ pointerEvents: 'none' }}>
          <Dropzone.Accept>
            <IconUpload style={{ width: rem(compact ? 32 : 52), height: rem(compact ? 32 : 52) }} stroke={1.5} />
          </Dropzone.Accept>
          <Dropzone.Reject>
            <IconX style={{ width: rem(compact ? 32 : 52), height: rem(compact ? 32 : 52) }} stroke={1.5} />
          </Dropzone.Reject>
          <Dropzone.Idle>
            <IconFileTypePdf style={{ width: rem(compact ? 32 : 52), height: rem(compact ? 32 : 52) }} stroke={1.5} />
          </Dropzone.Idle>
          <div>
            <Text size={compact ? 'md' : 'xl'} inline>
              {compact
                ? 'Добавить ещё том этого объекта (PDF)'
                : 'Перетащите PDF томов «Технологические решения» или нажмите для выбора'}
            </Text>
            <Text size="sm" c="dimmed" inline mt={7}>
              {compact
                ? 'Например, ТХ2 (пищеблок) к уже загруженному ТХ1'
                : 'Можно несколько файлов сразу — ТХ1 и ТХ2 одного объекта попадут в одну спецификацию. До 100 МБ каждый.'}
            </Text>
          </div>
        </Group>
      </Dropzone>

      {progress && (
        <Stack gap={4}>
          <Text size="sm">
            Разбираем {progress.current}
            {progress.total > 1 && ` (${progress.done + 1} из ${progress.total})`}…
          </Text>
          <Progress value={progress.total > 1 ? (progress.done / progress.total) * 100 : 100} animated />
        </Stack>
      )}

      {engineDown && (
        <Alert color="orange" title="Ядро разбора не отвечает" icon={<IconX size={18} />}>
          API работает, но Python-сервис разбора (порт 8000) недоступен — загрузка завершится ошибкой, пока он не поднят.
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
            <List.Item>Находит в PDF листы «Спецификация технологического оборудования» и читает таблицу.</List.Item>
            <List.Item>Сводит одинаковые позиции из разных помещений и считает общее количество.</List.Item>
            <List.Item>Даёт поправить свод, проставить разделы и цены, исключить лишнее — и выгружает Excel по форме КП.</List.Item>
            <List.Item>
              Сканы без текстового слоя распознаются через OCR:{' '}
              {ocr === undefined ? '…' : ocr ? `доступен (${ocr})` : 'на сервере не установлен, такие страницы будут пропущены'}
              .
            </List.Item>
          </List>
        </Alert>
      )}
    </Stack>
  )
}
