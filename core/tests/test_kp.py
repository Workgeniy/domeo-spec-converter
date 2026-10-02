from __future__ import annotations

import io

from openpyxl import load_workbook

from app.export.excel import build_workbook
from app.export.kp import price_row, totals
from app.models import ExportRequest, KpSettings, SummaryItem


def settings(**overrides) -> KpSettings:
    base = dict(vat_rate=0.2, markup_percent=10, installation_percent=5)
    base.update(overrides)
    return KpSettings(**base)


def test_price_row_applies_markup_delivery_and_installation() -> None:
    p = price_row(1000, settings())
    assert (p.sale, p.installation, p.unit_total) == (1100.0, 55.0, 1155.0)
    # Доставка входит в цену товара, СМР только у позиций с монтажом.
    d = price_row(1000, settings(delivery_percent=2))
    assert (d.sale, d.installation, d.unit_total) == (1122.0, 56.1, 1178.1)
    inv = price_row(1000, settings(delivery_percent=2), with_installation=False)
    assert (inv.sale, inv.installation, inv.unit_total) == (1122.0, 0.0, 1122.0)
    # Половина округляется вверх, как в интерфейсе (Math.round), а не по-банковски.
    h = price_row(1000, settings(markup_percent=15, installation_percent=7, round_to_ruble=True))
    assert (h.sale, h.installation, h.unit_total) == (1150.0, 81.0, 1231.0)


def test_totals_skip_unpriced_rows_and_split_sheets() -> None:
    rows = [
        SummaryItem(pos="1", qty=2, price=1000),
        SummaryItem(pos="2", qty=3, price=None),
        SummaryItem(pos="3", qty=4, price=500, installation=False),
    ]
    t = totals(rows, settings())
    assert (t.positions, t.mounted, t.inventory, t.priced) == (3, 2, 1, 2)
    assert t.goods_with_vat == 4400.0  # 2 × 1100 + 4 × 550
    assert t.goods_without_vat == 3666.67 and t.vat == 733.33
    assert t.installation == 110.0  # только строка с монтажом: 2 × 55
    assert t.total == 4510.0


def test_workbook_with_kp_matches_customer_sample() -> None:
    data = ExportRequest(
        file_name="объект.xlsx",
        title="Детский сад на 350 мест",
        summary=[
            SummaryItem(pos="2.1", section="Мебель", name="Стол", description="Стол воспитателя", unit="шт.", qty=14, price=1000),
            SummaryItem(pos="14.1", section="Игры и игрушки", name="Кукла", description="Кукла крупная", unit="шт.", qty=12, price=1000, installation=False),
            SummaryItem(pos="7.48", section="Оборудование пищеблока", name="Шкаф", description="Шкаф холодильный", unit="шт.", qty=1, price=50000),
            SummaryItem(pos="2.9", section="Мебель", name="Стул", description="Стул", unit="шт.", qty=5, price=None),
        ],
        kp=settings(contract_number="12/2026", contract_date="2026-09-01", customer_position="Директор", delivery_percent=2),
    )
    wb = build_workbook(data)
    # Только два листа, как в образце заказчика: приложения 1.1 и 1.2.
    assert wb.sheetnames == ["1", "2"]

    s1 = wb["1"]
    assert s1["B1"].value == "Приложение №1.1 к Договору № 12/2026 от 01.09.2026"
    assert s1["B2"].value == "Спецификация на Товар/Оборудование, подлежащего монтажу/пусконаладке"
    assert [s1.cell(3, c).value for c in (1, 8, 11, 13, 15)] == ["№", "Цена за ед. без НДС", "Цена за ед. СМР, с НДС", "Цена за ед. товара (вкл. СМР), с НДС", "Примечания Поставщика"]
    # Сквозная нумерация: позиции 1, 3, 4 на листе «1», позиция 2 — на листе «2».
    assert [s1.cell(r, 1).value for r in (4, 5, 6)] == [1, 3, 4]
    assert s1["K4"].value == 56.1 and s1["L4"].value == 0.2 and s1["M4"].value == 1178.1
    assert s1["H4"].value == "=J4/(1+L4)" and s1["N4"].value == "=F4*M4"
    assert s1["M6"].value is None  # без базовой цены графы КП пустые
    assert s1["M7"].value == "Итого с НДС" and s1["N7"].value == "=SUM(N4:N6)"
    assert s1["Q3"].value == "=N7" and [s1.cell(3, c).value for c in (18, 19, 20)] == ["пр", "дост", "монт"]
    assert [s1.cell(4, c).value for c in (18, 19, 20)] == [10, 2, 5]
    assert s1.auto_filter.ref == "A3:O6" and s1.row_dimensions[4].outline_level == 1
    # Подписи: «Подписи Сторон» через строку после итога, должность жирным, дальше только линии.
    assert s1["A9"].value == "Подписи Сторон"
    assert (s1["B12"].value, s1["F12"].value) == ("Заказчик:", "Поставщик:")
    assert (s1["B13"].value, s1["F13"].value) == ("Директор", "Генеральный директор") and s1["B13"].font.bold
    assert (s1["B14"].value, s1["B16"].value) == ("_______________________", "_______________________/")

    s2 = wb["2"]
    assert s2["B1"].value == "Приложение №1.2 к Договору № 12/2026 от 01.09.2026"
    assert s2["B2"].value == "Спецификация на Товар (инвентарь), не подлежащего монтажу/пусконаладке"
    assert [s2.cell(3, c).value for c in (8, 10, 11, 12, 13)] == ["Цена за ед. без НДС", "Ставка НДС", "Цена за ед. товара, с НДС", "Стоимость товара, с НДС", "Примечания Поставщика"]
    assert s2["A4"].value == 2 and s2["K4"].value == 1122.0 and s2["H4"].value == "=K4/(1+J4)" and s2["L4"].value == "=F4*K4"
    assert s2["K5"].value == "Всего с НДС" and s2["L5"].value == "=SUM(L4:L4)"
    assert s2["O3"].value == "=L5" and [s2.cell(4, c).value for c in (16, 17, 18)] == [10, 2, 0]
    assert s2["A7"].value == "Подписи Сторон"

    buffer = io.BytesIO()
    wb.save(buffer)
    load_workbook(io.BytesIO(buffer.getvalue()))


def test_workbook_without_kp_is_working_export() -> None:
    data = ExportRequest(summary=[SummaryItem(pos="1", qty=1, price=10), SummaryItem(pos="2", qty=1, installation=False)])
    wb = build_workbook(data)
    assert wb.sheetnames == ["Спецификация", "По помещениям", "Проверка"]
    ws = wb["Спецификация"]
    assert ws["M4"].value == 10 and ws["K4"].value is None and ws["L4"].value == 0.22  # НДС по умолчанию 22 %
    assert ws["A5"].value == 2  # без параметров КП все позиции на одном листе
    assert ws["Q3"].value == "=N6" and ws["R4"].value is None  # без параметров нет и граф-подсказок
