import { Badge, Button, HoverCard, NumberInput, ScrollArea, Table, Text, Tooltip } from '@mantine/core'
import { memo } from 'react'

import type { HistoryPrice, MatchKind, PriceSource } from '../api'
import type { HistoryChoice, RowKey, SummaryRow as Row } from '../store'
import { formatMoney, formatQty } from './format'

interface Props {
  number: number
  row: Row
  rowKey: RowKey
  onChange: (key: RowKey, patch: Partial<Row>) => void
  onChoose: (keys: RowKey[], which: HistoryChoice) => void
}

const KIND_LABEL: Record<MatchKind, { label: string; color: string }> = {
  exact: { label: 'точно', color: 'green' },
  fuzzy: { label: 'похоже', color: 'teal' },
  analog: { label: 'аналог', color: 'orange' },
  none: { label: 'не найдено', color: 'gray' },
}

const SOURCE_LABEL: Record<PriceSource, string> = {
  '': '',
  manual: 'вручную',
  history_min: 'мин',
  history_max: 'макс',
  history_median: 'медиана',
  history_last: 'последняя',
  internet: 'интернет',
}

function toNumber(value: number | string): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function MatchCell({ history }: { history: HistoryPrice | null }) {
  if (!history) {
    return (
      <Text size="xs" c="dimmed">
        не сопоставлено
      </Text>
    )
  }
  const look = KIND_LABEL[history.kind]
  const best = history.best
  return (
    <HoverCard width={560} shadow="md" withArrow openDelay={200} disabled={!best}>
      <HoverCard.Target>
        <div style={{ cursor: best ? 'help' : 'default' }}>
          <Badge size="xs" color={look.color} variant={history.kind === 'analog' ? 'filled' : 'light'}>
            {look.label}
            {best && history.kind !== 'exact' && ` · ${Math.round(best.score * 100)}%`}
          </Badge>
          {best && (
            <Text size="xs" lineClamp={2} mt={2}>
              {best.name}
            </Text>
          )}
        </div>
      </HoverCard.Target>
      <HoverCard.Dropdown>
        <ScrollArea.Autosize mah={360}>
          <Text size="xs" fw={600} mb={4}>
            Кандидаты из истории
          </Text>
          {history.candidates.map((c) => (
            <Text key={c.key} size="xs">
              {Math.round(c.score * 100)}% · {c.name} — {formatMoney(c.price_min)} … {formatMoney(c.price_max)} ({c.purchases} закуп.)
              {c.group && (
                <Text span c="dimmed">
                  {' '}
                  · {c.group}
                </Text>
              )}
            </Text>
          ))}
          {best && best.descriptions.length > 0 && (
            <Text size="xs" c="dimmed" mt={6}>
              Описание в истории: {best.descriptions[0]}
            </Text>
          )}
          {history.purchases.length > 0 && (
            <>
              <Text size="xs" fw={600} mt={8} mb={4}>
                Последние покупки «{best?.name}»
              </Text>
              <Table fz="xs" verticalSpacing={2} withRowBorders={false}>
                <Table.Tbody>
                  {history.purchases.map((p, i) => (
                    <Table.Tr key={i} style={{ opacity: p.outlier ? 0.5 : 1 }}>
                      <Table.Td>{p.purchased_at ?? '—'}</Table.Td>
                      <Table.Td ta="right">{formatMoney(p.unit_price)}</Table.Td>
                      <Table.Td ta="right">{formatQty(p.qty)} шт.</Table.Td>
                      <Table.Td>{p.partner_item || '—'}</Table.Td>
                      <Table.Td>{p.outlier ? 'выброс' : ''}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </>
          )}
        </ScrollArea.Autosize>
      </HoverCard.Dropdown>
    </HoverCard>
  )
}

function PriceChoice({ label, value, active, onClick }: { label: string; value: number | null; active: boolean; onClick: () => void }) {
  if (value === null) {
    return (
      <Text size="sm" c="dimmed" ta="right">
        —
      </Text>
    )
  }
  return (
    <Tooltip label={`Взять ${label} в базовую цену`}>
      <Button size="compact-xs" variant={active ? 'filled' : 'subtle'} color={active ? 'blue' : 'gray'} fullWidth onClick={onClick} styles={{ inner: { justifyContent: 'flex-end' } }}>
        {formatMoney(value)}
      </Button>
    </Tooltip>
  )
}

export const CostRowView = memo(function CostRowView({ number, row, rowKey, onChange, onChoose }: Props) {
  const best = row.history?.best ?? null
  const source = row.price_source ?? ''
  const total = row.price === null || row.qty === null ? null : row.price * row.qty
  const excluded = row.excluded === true

  return (
    <Table.Tr style={{ opacity: excluded ? 0.45 : 1 }}>
      <Table.Td>
        <Text size="sm" c="dimmed">
          {number}
        </Text>
      </Table.Td>
      <Table.Td>
        <Text size="sm" fw={500}>
          {row.pos}
        </Text>
      </Table.Td>
      <Table.Td>
        <Text size="sm" lineClamp={2} title={row.description}>
          {row.name}
        </Text>
        {row.section && (
          <Text size="xs" c="dimmed">
            {row.section}
          </Text>
        )}
      </Table.Td>
      <Table.Td>
        <Text size="sm" ta="right">
          {formatQty(row.qty)} {row.unit}
        </Text>
      </Table.Td>
      <Table.Td>
        <MatchCell history={row.history ?? null} />
      </Table.Td>
      <Table.Td>
        <Text size="sm" ta="right" c="dimmed">
          {row.internet_price === null || row.internet_price === undefined ? '—' : formatMoney(row.internet_price)}
        </Text>
      </Table.Td>
      <Table.Td>
        <PriceChoice label="минимум по истории" value={best?.price_min ?? null} active={source === 'history_min'} onClick={() => onChoose([rowKey], 'min')} />
      </Table.Td>
      <Table.Td>
        <PriceChoice label="максимум по истории" value={best?.price_max ?? null} active={source === 'history_max'} onClick={() => onChoose([rowKey], 'max')} />
      </Table.Td>
      <Table.Td>
        <PriceChoice label="последнюю закупку" value={best?.price_last ?? null} active={source === 'history_last'} onClick={() => onChoose([rowKey], 'last')} />
        {best?.last_date && (
          <Text size="xs" c="dimmed" ta="right">
            {best.last_date}
          </Text>
        )}
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
        {source && (
          <Text size="xs" c="dimmed" ta="right">
            {SOURCE_LABEL[source]}
          </Text>
        )}
      </Table.Td>
      <Table.Td>
        <Text size="sm" ta="right" c={total === null ? 'dimmed' : undefined}>
          {formatMoney(total)}
        </Text>
      </Table.Td>
    </Table.Tr>
  )
})
