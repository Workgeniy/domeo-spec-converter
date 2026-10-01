from __future__ import annotations

import io

from openpyxl import Workbook

from app.parsing.document import is_supported, parse_document
from app.parsing.xlsx_spec import parse_xlsx


def _book(header: list[str], rows: list[list[object]], before: list[str] | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Спецификация"
    for line in before or []:
        ws.append([line])
    ws.append(header)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_columns_found_by_header_in_any_order() -> None:
    # Порядок столбцов перепутан: кол-во первым, поз. в середине — ищем по словам шапки.
    data = _book(
        ["Кол-во", "Примечание", "Наименование и техническая характеристика", "Поз.", "Ед. изм.", "Тип, марка", "Завод-изготовитель"],
        [
            [2, "в углу", "Стол производственный, нержавеющая сталь, 1000х600х870", "7.124", "шт.", "СР-1000", "Торговая сеть"],
            [1, "", "Шкаф холодильный среднетемпературный 700 л", "7.48", "шт.", "по типу Polair CM107-S", "Торговая сеть"],
        ],
        before=["Спецификация технологического оборудования пищеблока, шифр ДОО350-ДОН-ПИР-П-ТХ7"],
    )
    doc = parse_xlsx(data, file_name="спец.xlsx")
    assert doc.doc_code == "ДОО350-ДОН-ПИР-П-ТХ7"
    assert [p.source for p in doc.pages] == ["xlsx"] and doc.pages[0].rows == 2
    assert len(doc.summary) == 2
    stol, shkaf = doc.summary
    assert (stol.pos, stol.qty, stol.unit, stol.type_mark) == ("7.124", 2.0, "шт.", "СР-1000")
    assert stol.name == "Стол производственный" and "нержавеющая сталь" in stol.description
    assert (shkaf.pos, shkaf.qty, shkaf.type_mark) == ("7.48", 1.0, "по типу Polair CM107-S")
    assert shkaf.section == "Оборудование пищеблока"  # из «пищеблок» в названии спецификации


def test_group_header_rows_and_missing_qty() -> None:
    data = _book(
        ["Поз.", "Наименование", "Ед.", "Кол-во"],
        [
            ["", "Раздел 1. Мебель", "", ""],  # строка-заголовок раздела
            ["1.1", "Стол письменный", "шт.", 3],
            ["1.2", "Стул офисный", "шт.", ""],  # количество не указано
        ],
    )
    doc = parse_xlsx(data, file_name="мебель.xlsx")
    assert [s.section for s in doc.summary] == ["Раздел 1. Мебель", "Раздел 1. Мебель"]
    assert doc.summary[0].qty == 3.0 and doc.summary[1].qty is None
    assert any("количество" in w for it in doc.items for w in it.warnings)


def test_alternative_header_words() -> None:
    # Другие формулировки заголовков: «№», «Наименование оборудования», «Количество».
    data = _book(["№ п/п", "Наименование оборудования", "Единица", "Количество", "Артикул"], [["1", "Мойка нержавеющая", "шт.", 4, "ВМ-1"]])
    doc = parse_xlsx(data, file_name="к.xlsx")
    assert len(doc.summary) == 1
    assert doc.summary[0].qty == 4.0 and doc.summary[0].type_mark == "ВМ-1"


def test_not_a_specification_sheet() -> None:
    data = _book(["Дата", "Сумма", "Контрагент"], [["01.01.2026", 1000, "ООО Ромашка"]])
    doc = parse_xlsx(data, file_name="платежи.xlsx")
    assert doc.summary == [] and doc.pages == []
    assert any("не найдено" in w for w in doc.warnings)


def test_merged_cells_expand() -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["Поз.", "Наименование", "Ед.", "Кол-во"])
    ws.append(["1.1", "Стеллаж производственный", "шт.", 2])
    ws.append(["1.2", "Стеллаж производственный", "шт.", 2])
    ws.merge_cells("D2:D3")  # количество одно на две строки
    ws["D2"] = 2
    buf = io.BytesIO()
    wb.save(buf)
    doc = parse_xlsx(buf.getvalue(), file_name="стеллажи.xlsx")
    assert [s.qty for s in doc.summary] == [2.0, 2.0]


def test_dispatch_by_extension() -> None:
    assert is_supported("том.pdf") and is_supported("Спец.XLSX") and is_supported("с.xlsm")
    assert not is_supported("данные.csv") and not is_supported("рисунок.png")
    data = _book(["Поз.", "Наименование", "Ед.", "Кол-во"], [["1", "Стол", "шт.", 1]])
    doc = parse_document(data, file_name="спец.xlsx")
    assert len(doc.summary) == 1 and doc.summary[0].name == "Стол"
