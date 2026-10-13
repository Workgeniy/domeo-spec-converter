import { Alert, Button, Fieldset, FileButton, Group, NumberInput, Paper, Select, SimpleGrid, Stack, Switch, Text, TextInput } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconAlertTriangle, IconFileDownload } from '@tabler/icons-react'
import { useMemo, useState } from 'react'

import { kpTotals } from '../kp'
import { useWorkspace } from '../store'
import { useTemplates } from '../templates'
import { readOriginal, type OriginalFile } from '../originals'
import { downloadBlob } from '../export'
import type { ParsedDocument } from '../api'
import { formatMoney } from './format'

interface Props {
  onDownload: () => void
  downloading: boolean
}

const VAT_OPTIONS = [
  { value: '0.22', label: 'НДС 22 %' },
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
  const { templates, selected, select, add, remove } = useTemplates()
  const [loadingTemplate, setLoadingTemplate] = useState(false)
  function templateError(error: unknown) {
    notifications.show({ color: 'red', title: 'Шаблон КП', message: error instanceof Error ? error.message : String(error) })
  }
  async function addTemplate(file: File | null) {
    if (!file) return
    setLoadingTemplate(true)
    try { await add(file) } catch (error) { templateError(error) }
    finally { setLoadingTemplate(false) }
  }
  async function useOriginal(original: OriginalFile, doc: ParsedDocument) {
    setLoadingTemplate(true)
    try {
      const existing = templates.find((t) => t.id === original.templateId)
      if (existing) select(existing.id)
      else await add(await readOriginal(original), doc)
    } catch (error) { templateError(error) }
    finally { setLoadingTemplate(false) }
  }
  async function downloadOriginal(original: OriginalFile) {
    try { downloadBlob(await readOriginal(original), original.name) }
    catch (error) { templateError(error) }
  }
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
      <Fieldset legend="Шаблон КП">
        <Stack gap="xs">
          <Group align="flex-end">
            <Select label="Форма выходного файла" style={{ flex: 1 }}
              data={[{ value: '', label: 'Стандартная форма — приложения 1.1 и 1.2' }, ...templates.map((t) => ({ value: t.id, label: t.name }))]}
              value={selected} allowDeselect={false} disabled={downloading || loadingTemplate}
              onChange={(id) => { if (id !== null) { try { select(id) } catch (error) { templateError(error) } } }} />
            <FileButton onChange={addTemplate} accept=".xlsx">
              {(props) => <Button {...props} variant="default" loading={loadingTemplate} disabled={downloading}>Загрузить шаблон</Button>}
            </FileButton>
            <Button variant="subtle" color="red" disabled={!selected || downloading || loadingTemplate}
              onClick={() => { try { remove() } catch (error) { templateError(error) } }}>Удалить шаблон</Button>
          </Group>
          <Text size="xs" c="dimmed">XLSX до 2 МБ. Одна таблица или два приложения (с СМР и без). Нужны заголовки «Наименование», «Кол во», цена за единицу с НДС, хотя бы одна строка-образец и строка «Итого» или «Всего». Библиотека шаблонов хранится в этом браузере. Выбранная форма автоматически сохраняется с объектом в базе и доступна при открытии на другом компьютере; каждая версия КП также хранит свою форму.</Text>
          <Text size="xs" c="dimmed">В шапке и подписях можно использовать {'{{contract_number}}, {{contract_date}}, {{title}}, {{supplier_position}}, {{customer_position}}'} — они заменятся параметрами КП.</Text>
          {documents.filter((d) => d.original).map((d) => (
            <Paper key={d.id} withBorder p="xs">
              <Group justify="space-between">
                <Text size="sm">Исходный файл: {d.original!.name}</Text>
                <Group gap="xs">
                  <Button size="compact-xs" variant="subtle" onClick={() => downloadOriginal(d.original!)}>Скачать исходник</Button>
                  <Button size="compact-xs" variant="light" disabled={downloading || loadingTemplate || !!d.original!.warning || !/\.xlsx$/i.test(d.original!.name)}
                    onClick={() => useOriginal(d.original!, d.doc)}>Использовать для КП</Button>
                </Group>
              </Group>
              {d.original!.warning && <Text size="xs" c="orange" mt={4}>Исходник сохранён, но его форма пока не подходит для КП: {d.original!.warning}</Text>}
            </Paper>
          ))}
          {!documents.some((d) => d.original) && <Text size="xs" c="dimmed">При новой загрузке Excel исходная форма запоминается автоматически. Для ранее загруженных документов потребуется повторно выбрать исходный файл.</Text>}
        </Stack>
      </Fieldset>
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
          <Button size="lg" leftSection={<IconFileDownload size={20} />} loading={downloading} onClick={onDownload} disabled={documents.length === 0 || loadingTemplate}>
            Сформировать КП (Excel)
          </Button>
        </Group>
        <Text size="xs" c="dimmed" mt="sm">
          {selected ? 'КП заполняется в выбранной форме. Сохраняются листы, оформление, шапка и подписи шаблона.' : 'Стандартная форма: лист «1» — с монтажом, лист «2» — инвентарь без монтажа. Лист выбирается галочкой «Монтаж» в своде.'}
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
            <Select label="Способ расчёта цены" allowDeselect={false}
              data={[{ value: 'margin', label: 'Целевая маржа на всё КП' }, { value: 'markup', label: 'Наценка (прежний расчёт)' }]}
              value={kp.margin_percent == null ? 'markup' : 'margin'}
              onChange={(v) => setKp({ margin_percent: v === 'margin' ? 0 : null })} />
            {kp.margin_percent != null && <NumberInput label="Целевая маржа, %" min={0} max={99.99} decimalScale={2}
              value={kp.margin_percent} onChange={(v) => setKp({ margin_percent: toNumber(v) })}
              description="Единая для всех товаров КП, с учётом доставки. Наценка дополнительно не применяется." />}
            <Group grow align="flex-start">
              <NumberInput disabled={kp.margin_percent != null} label="Наценка, %" min={-100} decimalScale={2} value={kp.markup_percent} onChange={(v) => setKp({ markup_percent: toNumber(v) })} />
              <NumberInput label="Доставка, %" description={kp.margin_percent == null ? "входит в цену" : "% от базовой себестоимости"} min={0} decimalScale={2} value={kp.delivery_percent} onChange={(v) => setKp({ delivery_percent: toNumber(v) })} />
              <NumberInput label="СМР, %" description="только лист «1»" min={0} decimalScale={2} value={kp.installation_percent} onChange={(v) => setKp({ installation_percent: toNumber(v) })} />
            </Group>
            <Switch label="Округлять цены в КП до рубля" checked={kp.round_to_ruble} onChange={(e) => setKp({ round_to_ruble: e.currentTarget.checked })} />
            <Text size="xs" c="dimmed">
              {kp.margin_percent != null
                ? 'Цена товара = базовая цена × (1 + доставка / 100) ÷ (1 − маржа / 100). При базе 100 ₽ и марже 20% без доставки цена — 125 ₽. В графу «пр» записывается эквивалентная наценка.'
                : 'Цена товара = базовая цена × (1 + наценка / 100) × (1 + доставка / 100).'}
              {' '}СМР начисляется отдельно процентом от цены товара. Маржа относится к товару с доставкой: себестоимость СМР и накладные расходы здесь не учитываются.
              {' '}Позиции без цены и количества не участвуют в расчёте; округление может немного изменить фактическую маржу.
            </Text>
          </Stack>
        </Fieldset>
      </SimpleGrid>
    </Stack>
  )
}
