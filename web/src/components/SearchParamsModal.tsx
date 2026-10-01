import { ActionIcon, Autocomplete, Button, Group, Modal, Stack, Text, Tooltip } from '@mantine/core'
import { IconPlus, IconTrash, IconWorldSearch } from '@tabler/icons-react'
import { useEffect, useState } from 'react'

import type { SearchParam } from '../api'

// Пределы те же, что проверяют обвязка и ядро.
export const MAX_PARAMS = 10
const NAME_LIMIT = 60
const VALUE_LIMIT = 120

const NAMES = [
  'Материал',
  'Материал каркаса',
  'Материал ножек',
  'Материал столешницы',
  'Материал корпуса',
  'Материал фасадов',
  'Обивка',
  'Покрытие',
  'Цвет',
  'Цвет каркаса',
  'Производитель',
  'Модель / артикул',
  'Размер',
  'Объём',
  'Мощность',
]
const MATERIALS = [
  'металл',
  'нержавеющая сталь',
  'оцинкованная сталь',
  'алюминий',
  'хром',
  'дерево',
  'массив дерева',
  'берёза',
  'бук',
  'дуб',
  'сосна',
  'ЛДСП',
  'МДФ',
  'фанера',
  'пластик',
  'стекло',
  'искусственный камень',
  'ткань',
  'велюр',
  'экокожа',
  'кожа',
]
const COLOURS = ['белый', 'чёрный', 'серый', 'бежевый', 'коричневый', 'венге', 'дуб сонома', 'бук', 'орех', 'красный', 'синий', 'зелёный', 'жёлтый', 'оранжевый']
const PLACEHOLDERS: Record<string, string> = { Размер: '1200х600х750 мм', Объём: '20 л', Мощность: '2 кВт', Производитель: 'Abat' }

const norm = (text: string) => text.toLowerCase().replace(/ё/g, 'е')

/** Материалы и цвета, которые уже названы в характеристиках позиции, — добавить одним щелчком. */
function fromDescription(description: string, items: SearchParam[]): SearchParam[] {
  const text = ` ${norm(description).replace(/[^а-яa-z0-9]+/g, ' ')}`
  const taken = new Set(items.map((p) => norm(p.value.trim())))
  const found: SearchParam[] = []
  for (const [name, values] of [
    ['Материал', MATERIALS],
    ['Цвет', COLOURS],
  ] as const) {
    for (const value of values) {
      const v = norm(value)
      // Слово с начала: «металл» найдётся и в «металлический»; уже найденное длинное («нержавеющая сталь») не дублируем.
      if (text.includes(` ${v}`) && !taken.has(v) && !found.some((f) => norm(f.value).includes(v))) found.push({ name, value })
    }
  }
  return found
}

function valueOptions(name: string): string[] {
  const n = name.toLowerCase()
  if (/цвет|оттен|декор/.test(n)) return COLOURS
  if (/материал|обивк|покрыт|каркас|ножк|столешниц|корпус|фасад|сиден|спинк/.test(n)) return MATERIALS
  return []
}

/** Без пустых значений и лишних пробелов — в том виде, в каком параметры сохраняются и уходят в поиск. */
export function cleanParams(params: SearchParam[]): SearchParam[] {
  const seen = new Set<string>()
  const result: SearchParam[] = []
  for (const p of params) {
    const name = p.name.replace(/\s+/g, ' ').trim().slice(0, NAME_LIMIT)
    const value = p.value.replace(/\s+/g, ' ').trim().slice(0, VALUE_LIMIT)
    const key = `${name.toLowerCase()}=${value.toLowerCase()}`
    if (!value || seen.has(key)) continue
    seen.add(key)
    result.push({ name, value })
  }
  return result.slice(0, MAX_PARAMS)
}

/** Те же ли параметры (порядок и регистр не важны) — чтобы видеть, что цену искали с другими. */
export function sameParams(a: SearchParam[], b: SearchParam[]): boolean {
  const key = (list: SearchParam[]) =>
    cleanParams(list)
      .map((p) => `${p.name.toLowerCase().replace(/ё/g, 'е')}=${p.value.toLowerCase().replace(/ё/g, 'е')}`)
      .sort()
      .join('|')
  return key(a) === key(b)
}

export function paramLabel(p: SearchParam): string {
  return p.name ? `${p.name}: ${p.value}` : p.value
}

interface Props {
  /** Ключ строки: пока окно открыто для той же позиции, правки не сбрасываются фоновым поиском. */
  rowId: string | null
  name: string
  /** Характеристики позиции — из них подсказываются материал и цвет. */
  description: string
  params: SearchParam[]
  canSearch: boolean
  onClose: () => void
  onSave: (params: SearchParam[], search: boolean) => void
}

/** Параметры поиска цены по позиции: материал, материал ножек, цвет, производитель… */
export function SearchParamsModal({ rowId, name, description, params, canSearch, onClose, onSave }: Props) {
  const [items, setItems] = useState<SearchParam[]>([])

  useEffect(() => {
    if (rowId) setItems(params.length > 0 ? params.map((p) => ({ ...p })) : [{ name: 'Материал', value: '' }])
    // Правки сбрасываются только при открытии для другой позиции, не при обновлении строки фоновым поиском.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rowId])

  const set = (i: number, patch: Partial<SearchParam>) => setItems((list) => list.map((p, j) => (j === i ? { ...p, ...patch } : p)))
  const cleaned = cleanParams(items)
  const suggested = fromDescription(description, items)
  // Подсказку кладём в пустую строку, если она есть, иначе — новой строкой.
  const addSuggested = (p: SearchParam) =>
    setItems((list) => {
      const empty = list.findIndex((x) => !x.value.trim())
      return empty >= 0 ? list.map((x, j) => (j === empty ? { ...p } : x)) : [...list, { ...p }].slice(0, MAX_PARAMS)
    })

  return (
    <Modal opened={rowId !== null} onClose={onClose} title="Параметры поиска цены" size="lg" transitionProps={{ duration: 0 }}>
      <Stack gap="sm">
        <Text size="sm" fw={500} lineClamp={2}>
          {name}
        </Text>
        <Text size="xs" c="dimmed">
          Параметры уходят в поисковый запрос и сверяются с названиями предложений. Где они подтвердились — цена по этим предложениям;
          где противоречат (другой материал, цвет) — в цену не входят; где не указаны — входят с пометкой «проверьте». Числа — с
          единицами: 20 л, 2 кВт, 1200х600 мм.
        </Text>
        {items.map((p, i) => (
          <Group key={i} gap="xs" wrap="nowrap" align="flex-start">
            <Autocomplete
              w={200}
              size="xs"
              placeholder="Параметр"
              data={NAMES}
              value={p.name}
              maxLength={NAME_LIMIT}
              onChange={(v) => set(i, { name: v })}
              aria-label="Параметр"
            />
            <Autocomplete
              style={{ flex: 1 }}
              size="xs"
              placeholder={PLACEHOLDERS[p.name] ?? 'Значение, например: металл'}
              data={valueOptions(p.name)}
              value={p.value}
              maxLength={VALUE_LIMIT}
              onChange={(v) => set(i, { value: v })}
              aria-label="Значение"
              data-autofocus={i === items.length - 1 ? true : undefined}
            />
            <Tooltip label="Убрать параметр">
              <ActionIcon variant="subtle" color="red" onClick={() => setItems((list) => list.filter((_, j) => j !== i))} aria-label="Убрать параметр">
                <IconTrash size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
        ))}
        <Group>
          <Button
            size="compact-sm"
            variant="subtle"
            leftSection={<IconPlus size={14} />}
            disabled={items.length >= MAX_PARAMS}
            onClick={() => setItems((list) => [...list, { name: '', value: '' }])}
          >
            Добавить параметр
          </Button>
        </Group>
        {suggested.length > 0 && (
          <Group gap={6}>
            <Text size="xs" c="dimmed">
              Из характеристик:
            </Text>
            {suggested.map((p) => (
              <Button key={`${p.name}=${p.value}`} size="compact-xs" variant="light" color="grape" onClick={() => addSuggested(p)}>
                + {paramLabel(p)}
              </Button>
            ))}
          </Group>
        )}
        <Group justify="space-between" mt="sm">
          <Button variant="subtle" color="gray" onClick={() => setItems([])} disabled={items.length === 0}>
            Убрать все
          </Button>
          <Group gap="xs">
            <Button variant="default" onClick={onClose}>
              Отмена
            </Button>
            <Button variant="light" onClick={() => onSave(cleaned, false)}>
              Сохранить
            </Button>
            <Tooltip label={canSearch ? 'Сохранить и сразу найти цену с этими параметрами' : 'Поиск цен не настроен'}>
              <Button leftSection={<IconWorldSearch size={16} />} disabled={!canSearch} onClick={() => onSave(cleaned, true)}>
                Сохранить и найти
              </Button>
            </Tooltip>
          </Group>
        </Group>
      </Stack>
    </Modal>
  )
}
