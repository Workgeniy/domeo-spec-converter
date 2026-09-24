import { Alert, Group, List, Loader, Stack, Text, rem } from '@mantine/core'
import { Dropzone, PDF_MIME_TYPE } from '@mantine/dropzone'
import { IconFileTypePdf, IconInfoCircle, IconUpload, IconX } from '@tabler/icons-react'
import { useEffect, useState } from 'react'

import { getHealth, parsePdf, type ParsedDocument } from '../api'

interface Props {
  onParsed: (doc: ParsedDocument) => void
}

export function UploadPane({ onParsed }: Props) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ocr, setOcr] = useState<string | null | undefined>(undefined)

  useEffect(() => {
    getHealth()
      .then((h) => setOcr(h.ocr))
      .catch(() => setOcr(null))
  }, [])

  async function handleDrop(files: File[]) {
    const file = files[0]
    if (!file) return
    setError(null)
    setBusy(file.name)
    try {
      onParsed(await parsePdf(file))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Stack gap="md" maw={820} mx="auto" mt="xl">
      <Dropzone
        onDrop={handleDrop}
        accept={PDF_MIME_TYPE}
        maxSize={100 * 1024 ** 2}
        multiple={false}
        loading={busy !== null}
      >
        <Group justify="center" gap="xl" mih={200} style={{ pointerEvents: 'none' }}>
          <Dropzone.Accept>
            <IconUpload style={{ width: rem(52), height: rem(52) }} stroke={1.5} />
          </Dropzone.Accept>
          <Dropzone.Reject>
            <IconX style={{ width: rem(52), height: rem(52) }} stroke={1.5} />
          </Dropzone.Reject>
          <Dropzone.Idle>
            <IconFileTypePdf style={{ width: rem(52), height: rem(52) }} stroke={1.5} />
          </Dropzone.Idle>
          <div>
            <Text size="xl" inline>
              Перетащите PDF тома «Технологические решения» или нажмите для выбора
            </Text>
            <Text size="sm" c="dimmed" inline mt={7}>
              Один файл до 100 МБ. Разбор занимает от секунд до минуты в зависимости от объёма.
            </Text>
          </div>
        </Group>
      </Dropzone>

      {busy && (
        <Group gap="sm">
          <Loader size="sm" />
          <Text size="sm">Разбираем {busy}…</Text>
        </Group>
      )}

      {error && (
        <Alert color="red" title="Не получилось" icon={<IconX size={18} />}>
          {error}
        </Alert>
      )}

      <Alert variant="light" color="gray" icon={<IconInfoCircle size={18} />} title="Что делает сервис">
        <List size="sm" spacing={4}>
          <List.Item>Находит в PDF листы «Спецификация технологического оборудования» и читает таблицу.</List.Item>
          <List.Item>Сводит одинаковые позиции из разных помещений и считает общее количество.</List.Item>
          <List.Item>Выгружает Excel по форме приложения к договору с формулами цен и листом замечаний.</List.Item>
          <List.Item>
            Сканы без текстового слоя распознаются через OCR:{' '}
            {ocr === undefined ? '…' : ocr ? `доступен (${ocr})` : 'на сервере не установлен, такие страницы будут пропущены'}
            .
          </List.Item>
        </List>
      </Alert>
    </Stack>
  )
}
