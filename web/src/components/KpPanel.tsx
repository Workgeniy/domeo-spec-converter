import { Alert, Button, Fieldset, Group, NumberInput, Paper, Select, SimpleGrid, Stack, Switch, Table, Text, TextInput, Textarea } from '@mantine/core'
import { IconAlertTriangle, IconFileDownload } from '@tabler/icons-react'
import { useMemo } from 'react'

import type { Party } from '../api'
import { kpTotals } from '../kp'
import { useWorkspace } from '../store'
import { formatMoney } from './format'

interface Props {
  onDownload: () => void
  downloading: boolean
}

const VAT_OPTIONS = [
  { value: '0.2', label: 'НДС 20 %' },
  { value: '0.1', label: 'НДС 10 %' },
  { value: '0', label: 'без НДС' },
]

function toNumber(value: number | string, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

export function KpPanel({ onDownload, downloading }: Props) {
  const kp = useWorkspace((s) => s.kp)
  const setKp = useWorkspace((s) => s.setKp)
  const setKpParty = useWorkspace((s) => s.setKpParty)
  const documents = useWorkspace((s) => s.documents)

  const totals = useMemo(() => {
    const rows = documents.flatMap((d) => d.doc.summary.filter((r) => !r.excluded))
    return kpTotals(rows, kp)
  }, [documents, kp])
  const unpriced = totals.positions - totals.priced

  const party = (side: 'supplier' | 'customer', title: string) => {
    const value: Party = kp[side]
    return (
      <Fieldset legend={title}>
        <Stack gap="xs">
          <TextInput label="Организация" placeholder="ООО «…»" value={value.name} onChange={(e) => setKpParty(side, { name: e.currentTarget.value })} />
          <TextInput
            label="Подписант"
            placeholder="Генеральный директор Иванов И.И."
            value={value.director}
            onChange={(e) => setKpParty(side, { director: e.currentTarget.value })}
          />
          <TextInput label="Контакты" placeholder="телефон, почта" value={value.contacts} onChange={(e) => setKpParty(side, { contacts: e.currentTarget.value })} />
        </Stack>
      </Fieldset>
    )
  }

  return (
    <SimpleGrid cols={{ base: 1, lg: 3 }} spacing="md">
      <Stack gap="md" style={{ gridColumn: 'span 2' }}>
        <Fieldset legend="Предложение">
          <Group grow align="flex-start">
            <TextInput label="Номер КП" placeholder="КП-2026-017" value={kp.number} onChange={(e) => setKp({ number: e.currentTarget.value })} />
            <TextInput label="Дата" type="date" value={kp.date} onChange={(e) => setKp({ date: e.currentTarget.value })} />
            <NumberInput label="Действительно, дней" min={0} value={kp.valid_days} onChange={(v) => setKp({ valid_days: Math.round(toNumber(v, 30)) })} />
          </Group>
          <Group grow align="flex-start" mt="xs">
            <TextInput
              label="Договор №"
              description="для шапки «Приложение №1.1 к Договору»"
              value={kp.contract_number}
              onChange={(e) => setKp({ contract_number: e.currentTarget.value })}
            />
            <TextInput label="Дата договора" type="date" value={kp.contract_date} onChange={(e) => setKp({ contract_date: e.currentTarget.value })} />
          </Group>
        </Fieldset>

        <SimpleGrid cols={{ base: 1, md: 2 }}>
          {party('supplier', 'Поставщик (мы)')}
          {party('customer', 'Заказчик')}
        </SimpleGrid>

        <Fieldset legend="Правила расчёта">
          <Text size="xs" c="dimmed" mb="xs">
            Цена в КП = базовая цена × (1 + наценка); СМР — процент от цены в КП, идёт в графу K; доставка — отдельной строкой в итогах.
          </Text>
          <Group grow align="flex-start">
            <Select label="НДС" data={VAT_OPTIONS} value={String(kp.vat_rate)} onChange={(v) => v !== null && setKp({ vat_rate: Number(v) })} allowDeselect={false} />
            <NumberInput label="Наценка, %" min={-100} decimalScale={2} value={kp.markup_percent} onChange={(v) => setKp({ markup_percent: toNumber(v) })} />
            <NumberInput label="СМР, % от цены" min={0} decimalScale={2} value={kp.installation_percent} onChange={(v) => setKp({ installation_percent: toNumber(v) })} />
            <NumberInput label="Доставка, % от товара" min={0} decimalScale={2} value={kp.delivery_percent} onChange={(v) => setKp({ delivery_percent: toNumber(v) })} />
          </Group>
          <Switch mt="sm" label="Округлять цены в КП до рубля" checked={kp.round_to_ruble} onChange={(e) => setKp({ round_to_ruble: e.currentTarget.checked })} />
        </Fieldset>

        <Fieldset legend="Условия">
          <Textarea
            autosize
            minRows={3}
            placeholder="Срок поставки, порядок оплаты, гарантия, монтаж…"
            value={kp.terms}
            onChange={(e) => setKp({ terms: e.currentTarget.value })}
          />
        </Fieldset>
      </Stack>

      <Stack gap="md">
        <Paper withBorder p="md">
          <Text fw={700} mb="xs">
            Итоги предложения
          </Text>
          <Table fz="sm" withRowBorders={false} verticalSpacing={4}>
            <Table.Tbody>
              <Table.Tr>
                <Table.Td>Позиций в КП</Table.Td>
                <Table.Td ta="right">{totals.positions}</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>С ценой</Table.Td>
                <Table.Td ta="right">{totals.priced}</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>Товар без НДС</Table.Td>
                <Table.Td ta="right">{formatMoney(totals.goodsWithoutVat)}</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>НДС</Table.Td>
                <Table.Td ta="right">{formatMoney(totals.vat)}</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>Товар с НДС</Table.Td>
                <Table.Td ta="right">{formatMoney(totals.goodsWithVat)}</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>СМР с НДС</Table.Td>
                <Table.Td ta="right">{formatMoney(totals.installation)}</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>Доставка</Table.Td>
                <Table.Td ta="right">{formatMoney(totals.delivery)}</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>
                  <Text fw={700}>Итого по КП, с НДС</Text>
                </Table.Td>
                <Table.Td ta="right">
                  <Text fw={700}>{formatMoney(totals.total)}</Text>
                </Table.Td>
              </Table.Tr>
            </Table.Tbody>
          </Table>
        </Paper>

        {unpriced > 0 && (
          <Alert color="yellow" icon={<IconAlertTriangle size={18} />} title={`Без цены: ${unpriced} из ${totals.positions}`}>
            Эти позиции попадут в спецификацию с пустой ценой и не войдут в итоги. Проставьте базовую цену в своде (фильтр «Без цены»)
            или исключите их из КП.
          </Alert>
        )}

        <Button size="md" leftSection={<IconFileDownload size={18} />} loading={downloading} onClick={onDownload} disabled={documents.length === 0}>
          Сформировать КП (Excel)
        </Button>
        <Text size="xs" c="dimmed">
          В файле: лист «КП» (титул, итоги по разделам, условия, подписи), «Спецификация» по форме приложения к договору с ценами,
          «По помещениям» и «Проверка». Итоги в Excel — формулами, правки цен в файле пересчитываются.
        </Text>
      </Stack>
    </SimpleGrid>
  )
}
