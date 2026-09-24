from __future__ import annotations

import io

from openpyxl import load_workbook

from app.export.excel import build_workbook
from app.export.kp import price_row, totals, valid_until
from app.models import ExportRequest, KpSettings, Party, SummaryItem


def settings(**overrides) -> KpSettings:
    base = dict(number="17", date="24.09.2026", valid_days=30, vat_rate=0.2, markup_percent=10, installation_percent=5)
    base.update(overrides)
    return KpSettings(**base)


def test_price_row_applies_markup_and_installation() -> None:
    p = price_row(1000, settings())
    assert (p.sale, p.installation, p.unit_total) == (1100.0, 55.0, 1155.0)
    r = price_row(1234.5, settings(round_to_ruble=True))
    assert (r.sale, r.installation, r.unit_total) == (1358.0, 68.0, 1426.0)
    z = price_row(1234.5, settings(markup_percent=0, installation_percent=0))
    assert (z.sale, z.installation, z.unit_total) == (1234.5, 0.0, 1234.5)
    # Половина округляется вверх, как в интерфейсе (Math.round), а не по-банковски.
    h = price_row(1000, settings(markup_percent=15, installation_percent=7, round_to_ruble=True))
    assert (h.sale, h.installation, h.unit_total) == (1150.0, 81.0, 1231.0)


def test_totals_skip_unpriced_rows_and_add_delivery() -> None:
    rows = [
        SummaryItem(pos="1", qty=2, price=1000),
        SummaryItem(pos="2", qty=3, price=None),
        SummaryItem(pos="3", qty=None, price=500),
    ]
    t = totals(rows, settings(delivery_percent=3))
    assert (t.positions, t.priced) == (3, 1)
    assert t.goods_with_vat == 2200.0  # 2 × 1100
    assert t.goods_without_vat == 1833.33 and t.vat == 366.67
    assert t.installation == 110.0  # 2 × 55
    assert t.delivery == 66.0  # 3 % от 2200
    assert t.total == 2376.0


def test_valid_until() -> None:
    assert valid_until(settings(date="2026-09-24", valid_days=30)) == "24.10.2026"
    assert valid_until(settings(date="", valid_days=30)) == ""


def test_workbook_with_kp_sheet() -> None:
    data = ExportRequest(
        file_name="объект.xlsx",
        title="Детский сад на 350 мест",
        summary=[
            SummaryItem(pos="2.1", section="Мебель", name="Стол", description="Стол воспитателя", unit="шт.", qty=14, price=1000),
            SummaryItem(pos="7.48", section="Оборудование пищеблока", name="Шкаф", description="Шкаф холодильный", unit="шт.", qty=1, price=50000),
            SummaryItem(pos="2.9", section="Мебель", name="Стул", description="Стул", unit="шт.", qty=5, price=None),
        ],
        kp=settings(
            supplier=Party(name="ООО «Альянс»"),
            customer=Party(name="ООО «ПИК-Менеджмент»", position="Директор"),
            contract_number="12/2026",
            contract_date="2026-09-01",
            delivery_percent=2,
            terms="Срок поставки 30 дней. Оплата: аванс 50 %.",
        ),
    )
    wb = build_workbook(data)
    assert wb.sheetnames == ["КП", "Спецификация", "По помещениям", "Проверка"]

    spec = wb["Спецификация"]
    assert spec["B1"].value == "Приложение №1.1 к Договору № 12/2026 от 01.09.2026"
    assert spec["K4"].value == 55.0 and spec["L4"].value == 0.2 and spec["M4"].value == 1155.0
    assert spec["M6"].value is None  # без базовой цены графы КП пустые
    assert spec.auto_filter.ref == "A3:O6"
    assert spec.row_dimensions[4].outline_level == 1
    # Блок подписей по образцу: «Итого» в строке 7, «Подписи Сторон» через строку, затем стороны,
    # жирная должность, дальше только линии — организацию и подпись вписывают руками.
    assert spec["M7"].value == "Итого с НДС" and spec["A9"].value == "Подписи Сторон"
    assert (spec["B12"].value, spec["F12"].value) == ("Заказчик:", "Поставщик:")
    assert (spec["B13"].value, spec["F13"].value) == ("Директор", "Генеральный директор") and spec["B13"].font.bold
    assert (spec["B14"].value, spec["F14"].value) == ("_______________________", "_______________________")
    assert (spec["B16"].value, spec["F16"].value) == ("_______________________/", "_______________________/")
    assert "ООО «Альянс»" not in [c.value for row in spec.iter_rows(min_row=9) for c in row]

    kp = wb["КП"]
    assert kp["A1"].value == "КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ № 17 от 24.09.2026"
    values = [c.value for row in kp.iter_rows() for c in row if c.value is not None]
    assert "Мебель" in values and "Оборудование пищеблока" in values
    assert any(isinstance(v, str) and v.startswith("=SUMIF('Спецификация'!$B$4:$B$6") for v in values)
    assert any(isinstance(v, str) and "24.10.2026" in v for v in values)
    assert any(isinstance(v, str) and "нет цены" in v for v in values)

    # Файл читается обратно без ошибок
    buffer = io.BytesIO()
    wb.save(buffer)
    load_workbook(io.BytesIO(buffer.getvalue()))


def test_workbook_without_kp_keeps_old_layout() -> None:
    data = ExportRequest(summary=[SummaryItem(pos="1", qty=1, price=10)])
    wb = build_workbook(data)
    assert wb.sheetnames == ["Спецификация", "По помещениям", "Проверка"]
    assert wb["Спецификация"]["M4"].value == 10 and wb["Спецификация"]["K4"].value is None
