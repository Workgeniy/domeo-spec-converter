import { ActionIcon, Autocomplete, Checkbox, HoverCard, NumberInput, ScrollArea, Table, Text, TextInput, Textarea, Tooltip } from '@mantine/core'
import { IconArrowBackUp, IconTrash } from '@tabler/icons-react'
import { memo } from 'react'

import type { Indexation, KpSettings } from '../api'
import { kpBase, priceRow } from '../kp'
import type { RowKey, SummaryRow as Row } from '../store'
import { formatMoney, formatQty } from './format'

interface Props {
  number: number
  row: Row
  rowKey: RowKey
  selected: boolean
  showDoc: boolean
  sections: string[]
  kp: KpSettings
  indexation: Indexation
  onToggle: (key: string) => void
  onChange: (key: RowKey, patch: Partial<Row>) => void
}

function toNumber(value: number | string): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** «ДОО350-ДОН-ПИР-П-ТХ1» → «ТХ1»: в узкой графе хватает хвоста шифра, полный — в подсказке. */
function shortDocCode(code: string): string {
  const tail = code.split(/[-–]/).pop() ?? code
  return tail.trim() || code
}

/**
 * Строка свода. Мемоизирована: при правке одной ячейки в сторе меняется только объект
 * этой строки, остальные строки страницы не перерисовываются.
 */
export const SummaryRowView = memo(function SummaryRowView({ number, row, rowKey, selected, showDoc, sections, kp, indexation, onToggle, onChange }: Props) {
  const key = `${rowKey.docId}:${rowKey.index}`
  const excluded = row.excluded === true
  const hasWarnings = row.warnings.length > 0
  const installation = row.installation ?? true
  // База для КП — проиндексированная к дате поставки, если так настроено во вкладке «Себестоимость».
  const base = kpBase(row, indexation)
  const indexed = base !== null && row.price !== null && base !== row.price
  const kpPrice = base === null ? null : priceRow(base, kp, installation)
  const total = kpPrice === null || row.qty === null ? null : kpPrice.unitTotal * row.qty

  return (
    <Table.Tr
      style={{
        background: excluded ? 'var(--mantine-color-gray-1)' : hasWarnings ? 'var(--mantine-color-yellow-0)' : undefined,
        opacity: excluded ? 0.55 : 1,
      }}
    >
      <Table.Td>
        <Checkbox size="xs" checked={selected} onChange={() => onToggle(key)} aria-label="выбрать строку" />
      </Table.Td>
      <Table.Td>
        <Text size="sm" c="dimmed">
          {number}
        </Text>
      </Table.Td>
      <Table.Td>
        <Text size="sm" fw={500} td={excluded ? 'line-through' : undefined}>
          {row.pos}
        </Text>
        {showDoc && (
          <Tooltip label={row.source_doc} disabled={!row.source_doc}>
            <Text size="xs" c="dimmed" truncate>
              {shortDocCode(row.source_doc)}
            </Text>
          </Tooltip>
        )}
      </Table.Td>
      <Table.Td>
        <Autocomplete
          size="xs"
          variant="filled"
          data={sections}
          value={row.section}
          onChange={(section) => onChange(rowKey, { section })}
          placeholder="раздел КП"
          disabled={excluded}
          limit={20}
        />
      </Table.Td>
      <Table.Td>
        <TextInput size="xs" variant="filled" value={row.name} onChange={(e) => onChange(rowKey, { name: e.currentTarget.value })} disabled={excluded} />
      </Table.Td>
      <Table.Td>
        <Textarea
          size="xs"
          variant="filled"
          autosize
          minRows={1}
          maxRows={4}
          value={row.description}
          onChange={(e) => onChange(rowKey, { description: e.currentTarget.value })}
          disabled={excluded}
        />
        {hasWarnings && (
          <Text size="xs" c="orange.8" mt={2}>
            {row.warnings.join('; ')}
          </Text>
        )}
        {row.note && (
          <Text size="xs" c="dimmed" mt={2}>
            Примечание: {row.note}
          </Text>
        )}
      </Table.Td>
      <Table.Td>
        <TextInput size="xs" variant="filled" value={row.unit} onChange={(e) => onChange(rowKey, { unit: e.currentTarget.value })} disabled={excluded} />
      </Table.Td>
      <Table.Td>
        <NumberInput
          size="xs"
          variant="filled"
          hideControls
          decimalScale={3}
          value={row.qty ?? ''}
          onChange={(v) => onChange(rowKey, { qty: toNumber(v) })}
          disabled={excluded}
          styles={{ input: { textAlign: 'right' } }}
        />
      </Table.Td>
      <Table.Td>
        <HoverCard width={380} shadow="md" withArrow openDelay={150}>
          <HoverCard.Target>
            <Text size="sm" ta="center" style={{ cursor: 'help', textDecoration: 'underline dotted' }}>
              {row.groups.length}
            </Text>
          </HoverCard.Target>
          <HoverCard.Dropdown>
            <ScrollArea.Autosize mah={300}>
              {row.groups.map((g, i) => (
                <Text key={i} size="xs">
                  {g.group || '— без помещения —'}: <b>{formatQty(g.qty)}</b>
                </Text>
              ))}
            </ScrollArea.Autosize>
          </HoverCard.Dropdown>
        </HoverCard>
      </Table.Td>
      <Table.Td>
        <Tooltip label={installation ? 'Подлежит монтажу → лист «1» (Приложение №1.1)' : 'Инвентарь без монтажа → лист «2» (Приложение №1.2)'}>
          <Checkbox
            size="xs"
            checked={installation}
            onChange={(e) => onChange(rowKey, { installation: e.currentTarget.checked })}
            disabled={excluded}
            aria-label="подлежит монтажу"
            styles={{ body: { justifyContent: 'center' } }}
          />
        </Tooltip>
      </Table.Td>
      <Table.Td>
        <NumberInput
          size="xs"
          variant="filled"
          hideControls
          decimalScale={2}
          thousandSeparator=" "
          value={row.price ?? ''}
          onChange={(v) => onChange(rowKey, { price: toNumber(v), price_source: toNumber(v) === null ? '' : 'manual' })}
          placeholder="—"
          disabled={excluded}
          styles={{ input: { textAlign: 'right' } }}
        />
      </Table.Td>
      <Table.Td>
        <Tooltip
          label={
            kpPrice
              ? `товар ${formatMoney(kpPrice.sale)}${installation ? ` + СМР ${formatMoney(kpPrice.installation)}` : ''}${indexed ? ` · база проиндексирована к ${indexation.date}: ${formatMoney(base)}` : ''}`
              : 'нет базовой цены'
          }
          disabled={!kpPrice}
        >
          <Text size="sm" ta="right" c={kpPrice === null ? 'dimmed' : undefined}>
            {kpPrice === null ? '—' : formatMoney(kpPrice.unitTotal)}
          </Text>
        </Tooltip>
      </Table.Td>
      <Table.Td>
        <Text size="sm" ta="right" c={total === null ? 'dimmed' : undefined}>
          {formatMoney(total)}
        </Text>
      </Table.Td>
      <Table.Td>
        <Tooltip label={excluded ? 'Вернуть в КП' : 'Исключить из КП'}>
          <ActionIcon variant="subtle" color={excluded ? 'blue' : 'red'} onClick={() => onChange(rowKey, { excluded: !excluded })} aria-label="исключить">
            {excluded ? <IconArrowBackUp size={16} /> : <IconTrash size={16} />}
          </ActionIcon>
        </Tooltip>
      </Table.Td>
    </Table.Tr>
  )
})
