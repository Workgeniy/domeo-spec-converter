import { Alert, Button, Fieldset, Group, NumberInput, Paper, Select, SimpleGrid, Stack, Switch, Text, TextInput, Textarea } from '@mantine/core'
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

function Stat({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size={strong ? 'lg' : 'sm'} fw={strong ? 700 : 500}>
        {value}
      </Text>
    </div>
  )
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
            label="Должность подписанта"
            description="в подписях печатается только должность, организация и подпись — на линиях"
            placeholder="Генеральный директор"
            value={value.position}
            onChange={(e) => setKpParty(side, { position: e.currentTarget.value })}
          />
          <TextInput label="Контакты" placeholder="телефон, почта" value={value.contacts} onChange={(e) => setKpParty(side, { contacts: e.currentTarget.value })} />
        </Stack>
      </Fieldset>
    )
  }

  return (
    <Stack gap="md">
      {/* Итоги и кнопка — первыми, чтобы не искать их под формой. */}
      <Paper withBorder p="md">
        <Group justify="space-between" align="center" wrap="wrap" gap="lg">
          <Group gap="xl" wrap="wrap">
            <Stat label="Позиций в КП" value={`${totals.positions}`} />
            <Stat label="С ценой" value={`${totals.priced} из ${totals.positions}`} />
            <Stat label="Товар без НДС" value={formatMoney(totals.goodsWithoutVat)} />
            <Stat label="НДС" value={formatMoney(totals.vat)} />
            <Stat label="Товар с НДС" value={formatMoney(totals.goodsWithVat)} />
            <Stat label="СМР с НДС" value={formatMoney(totals.installation)} />
            <Stat label="Доставка" value={formatMoney(totals.delivery)} />
            <Stat label="Итого по КП, с НДС" value={`${formatMoney(totals.total)} ₽`} strong />
          </Group>
          <Button size="lg" leftSection={<IconFileDownload size={20} />} loading={downloading} onClick={onDownload} disabled={documents.length === 0}>
            Сформировать КП (Excel)
          </Button>
        </Group>
        <Text size="xs" c="dimmed" mt="sm">
          В файле: лист «КП» (титул, итоги по разделам, условия, подписи), «Спецификация» по форме приложения к договору с ценами, «По помещениям»
          и «Проверка». Итоги в Excel — формулами, правки цен в файле пересчитываются.
        </Text>
      </Paper>

      {unpriced > 0 && (
        <Alert color="yellow" icon={<IconAlertTriangle size={18} />} title={`Без цены: ${unpriced} из ${totals.positions}`}>
          Эти позиции попадут в спецификацию с пустой ценой и не войдут в итоги. Проставьте базовую цену в своде (фильтр «Без цены») или
          исключите их из КП.
        </Alert>
      )}

      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
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

        {party('supplier', 'Поставщик (мы)')}
        {party('customer', 'Заказчик')}
      </SimpleGrid>

      <Fieldset legend="Условия">
        <Textarea autosize minRows={3} placeholder="Срок поставки, порядок оплаты, гарантия, монтаж…" value={kp.terms} onChange={(e) => setKp({ terms: e.currentTarget.value })} />
      </Fieldset>
    </Stack>
  )
}
