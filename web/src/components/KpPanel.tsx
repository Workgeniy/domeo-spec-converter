import { Alert, Button, Fieldset, Group, NumberInput, Paper, Select, SimpleGrid, Stack, Switch, Text, TextInput } from '@mantine/core'
import { IconAlertTriangle, IconFileDownload } from '@tabler/icons-react'
import { useMemo } from 'react'

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
  const documents = useWorkspace((s) => s.documents)
  const indexation = useWorkspace((s) => s.indexation)

  const totals = useMemo(() => {
    const rows = documents.flatMap((d) => d.doc.summary.filter((r) => !r.excluded))
    return kpTotals(rows, kp, indexation)
  }, [documents, kp, indexation])
  const unpriced = totals.positions - totals.priced

  return (
    <Stack gap="md">
      {/* Итоги и кнопка — первыми, чтобы не искать их под формой. */}
      <Paper withBorder p="md">
        <Group justify="space-between" align="center" wrap="wrap" gap="lg">
          <Group gap="xl" wrap="wrap">
            <Stat label="Лист «1» (с монтажом)" value={`${totals.mounted} поз.`} />
            <Stat label="Лист «2» (инвентарь)" value={`${totals.inventory} поз.`} />
            <Stat label="С ценой" value={`${totals.priced} из ${totals.positions}`} />
            <Stat label="Товар без НДС" value={formatMoney(totals.goodsWithoutVat)} />
            <Stat label="НДС" value={formatMoney(totals.vat)} />
            <Stat label="Товар с НДС" value={formatMoney(totals.goodsWithVat)} />
            <Stat label="СМР с НДС" value={formatMoney(totals.installation)} />
            <Stat label="Итого с НДС" value={`${formatMoney(totals.total)} ₽`} strong />
          </Group>
          <Button size="lg" leftSection={<IconFileDownload size={20} />} loading={downloading} onClick={onDownload} disabled={documents.length === 0}>
            Сформировать КП (Excel)
          </Button>
        </Group>
        <Text size="xs" c="dimmed" mt="sm">
          Файл по образцу заказчика: лист «1» — Приложение №1.1 (товар/оборудование, подлежащее монтажу, с графами СМР), лист «2» —
          Приложение №1.2 (инвентарь без монтажа). Какая позиция на каком листе — галочка «Монтаж» в своде.
        </Text>
      </Paper>

      {unpriced > 0 && (
        <Alert color="yellow" icon={<IconAlertTriangle size={18} />} title={`Без цены: ${unpriced} из ${totals.positions}`}>
          Эти позиции попадут в приложения с пустыми ценовыми графами. Проставьте базовую цену в своде (фильтр «Без цены») или исключите
          их из КП.
        </Alert>
      )}

      <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
        <Fieldset legend="Договор">
          <Stack gap="xs">
            <TextInput
              label="Договор №"
              description="для шапки «Приложение №1.1 к Договору № … от …»"
              value={kp.contract_number}
              onChange={(e) => setKp({ contract_number: e.currentTarget.value })}
            />
            <TextInput label="Дата договора" type="date" value={kp.contract_date} onChange={(e) => setKp({ contract_date: e.currentTarget.value })} />
          </Stack>
        </Fieldset>

        <Fieldset legend="Подписанты">
          <Stack gap="xs">
            <TextInput
              label="Должность — Поставщик"
              placeholder="Генеральный директор"
              value={kp.supplier_position}
              onChange={(e) => setKp({ supplier_position: e.currentTarget.value })}
            />
            <TextInput
              label="Должность — Заказчик"
              placeholder="Генеральный директор"
              value={kp.customer_position}
              onChange={(e) => setKp({ customer_position: e.currentTarget.value })}
            />
            <Text size="xs" c="dimmed">
              В блоке подписей печатается только должность; организация и подпись — на линиях, от руки.
            </Text>
          </Stack>
        </Fieldset>

        <Fieldset legend="Правила расчёта">
          <Stack gap="xs">
            <Select label="НДС" data={VAT_OPTIONS} value={String(kp.vat_rate)} onChange={(v) => v !== null && setKp({ vat_rate: Number(v) })} allowDeselect={false} />
            <Group grow align="flex-start">
              <NumberInput label="Наценка, %" min={-100} decimalScale={2} value={kp.markup_percent} onChange={(v) => setKp({ markup_percent: toNumber(v) })} />
              <NumberInput label="Доставка, %" description="входит в цену" min={0} decimalScale={2} value={kp.delivery_percent} onChange={(v) => setKp({ delivery_percent: toNumber(v) })} />
              <NumberInput label="СМР, %" description="только лист «1»" min={0} decimalScale={2} value={kp.installation_percent} onChange={(v) => setKp({ installation_percent: toNumber(v) })} />
            </Group>
            <Switch label="Округлять цены в КП до рубля" checked={kp.round_to_ruble} onChange={(e) => setKp({ round_to_ruble: e.currentTarget.checked })} />
            <Text size="xs" c="dimmed">
              Цена в КП = базовая цена × (1 + наценка) × (1 + доставка); СМР — процент от цены в КП, графа K листа «1». Проценты
              записываются в графы «пр / дост / монт» за областью печати, как в образце.
            </Text>
          </Stack>
        </Fieldset>
      </SimpleGrid>
    </Stack>
  )
}
