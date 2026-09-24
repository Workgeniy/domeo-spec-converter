import { Badge, Group, Paper, SimpleGrid, Text, ThemeIcon } from '@mantine/core'
import { IconCheck, IconClock, IconPencil } from '@tabler/icons-react'

type Status = 'done' | 'manual' | 'later'

// Пять шагов конвейера из постановки заказчика. Пока автоматизирован первый, пятый
// доступен вручную (цены в своде), остальные — следующие этапы.
const STEPS: { title: string; status: Status; hint: string }[] = [
  { title: 'Извлечение из PDF', status: 'done', hint: 'таблица прочитана, свод собран' },
  { title: 'Сверка с чертежами', status: 'later', hint: 'позиции на планах против спецификации' },
  { title: 'Подбор по базе 1С', status: 'later', hint: 'артикул, поставщик, характеристики' },
  { title: 'Цены от–до', status: 'later', hint: 'база и открытые источники' },
  { title: 'Цена в КП', status: 'manual', hint: 'сейчас проставляется вручную в своде' },
]

const LOOK: Record<Status, { color: string; label: string; icon: React.ReactNode }> = {
  done: { color: 'green', label: 'готово', icon: <IconCheck size={14} /> },
  manual: { color: 'blue', label: 'вручную', icon: <IconPencil size={14} /> },
  later: { color: 'gray', label: 'следующий этап', icon: <IconClock size={14} /> },
}

export function PipelineBar() {
  return (
    <SimpleGrid cols={{ base: 1, sm: 2, md: 3, lg: 5 }} spacing="xs">
      {STEPS.map((step, i) => {
        const look = LOOK[step.status]
        return (
          <Paper key={step.title} withBorder p="xs" style={{ opacity: step.status === 'later' ? 0.7 : 1 }}>
            <Group gap={8} wrap="nowrap" align="flex-start">
              <ThemeIcon size="sm" radius="xl" color={look.color} variant={step.status === 'later' ? 'light' : 'filled'}>
                {look.icon}
              </ThemeIcon>
              <div style={{ minWidth: 0 }}>
                <Text size="sm" fw={600} lh={1.2}>
                  {i + 1}. {step.title}
                </Text>
                <Text size="xs" c="dimmed" lh={1.2} mt={2}>
                  {step.hint}
                </Text>
                <Badge size="xs" variant="light" color={look.color} mt={4}>
                  {look.label}
                </Badge>
              </div>
            </Group>
          </Paper>
        )
      })}
    </SimpleGrid>
  )
}
