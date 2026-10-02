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


def test_merged_qty_shared_between_two_items() -> None:
    # Две разные позиции (свои номера), количество общее на обе через объединение.
    wb = Workbook()
    ws = wb.active
    ws.append(["Поз.", "Наименование", "Ед.", "Кол-во"])
    ws.append(["1.1", "Стеллаж производственный 600", "шт.", 2])
    ws.append(["1.2", "Стеллаж производственный 800", "шт.", None])
    ws.merge_cells("D2:D3")
    ws["D2"] = 2
    buf = io.BytesIO()
    wb.save(buf)
    doc = parse_xlsx(buf.getvalue(), file_name="стеллажи.xlsx")
    assert [s.pos for s in doc.summary] == ["1.1", "1.2"] and [s.qty for s in doc.summary] == [2.0, 2.0]


def test_characteristics_fold_into_description() -> None:
    # Как в реальных спецификациях: номер/ед./кол объединены по вертикали на строку товара и
    # строки его характеристик — это одна позиция, характеристики уходят в описание.
    wb = Workbook()
    ws = wb.active
    ws.append(["Объект, шифр ДОО-ТХ9"])
    ws.append(["Поз.", "Наименование и техническая характеристика", "Тип, марка", "Поставщик", "Ед.", "Кол"])
    ws.append([None, "Пом. 120 Кладовая", None, None, None, None])  # заголовок помещения (в столбце наименования)
    ws.append(["П101", "Стол для белья", "С-1260 или аналог", "Вязьма, РФ", "шт.", 2])
    ws.append([None, "Габаритные размеры, мм: 1215х590х840", None, None, None, None])  # характеристика
    ws.append([None, "Электропитание: 1ф, 220 В", None, None, None, None])  # ещё характеристика
    ws.append(["П102", "Весы напольные", "МП 150 или аналог", "МИДЛ, РФ", "шт.", 1])
    ws.append([None, "Изделие соответствует ГОСТ 12345", None, None, None, None])  # незнакомая характеристика → не раздел
    # Объединяем «Ед.» и «Кол» на строку товара и его характеристики.
    ws.merge_cells("E4:E6")
    ws.merge_cells("F4:F6")
    buf = io.BytesIO()
    wb.save(buf)
    doc = parse_xlsx(buf.getvalue(), file_name="спец.xlsx")
    assert doc.doc_code == "ДОО-ТХ9"
    assert [s.pos for s in doc.summary] == ["П101", "П102"]  # характеристики не стали позициями
    stol = doc.summary[0]
    assert stol.qty == 2.0 and stol.unit == "шт." and stol.section == "Пом. 120 Кладовая"
    assert "Габаритные размеры, мм: 1215х590х840" in stol.description and "Электропитание" in stol.description
    # Незнакомая характеристика после П102 не создала раздел и не стала позицией.
    assert "Изделие соответствует ГОСТ 12345" in doc.summary[1].description
    assert all("ГОСТ 12345" not in (s.section or "") for s in doc.summary)


def test_qty_header_named_just_kol() -> None:
    # Столбец количества может называться ровно «Кол».
    data = _book(["Поз.", "Наименование", "Ед.", "Кол"], [["1", "Стол", "шт.", 3]])
    doc = parse_xlsx(data, file_name="к.xlsx")
    assert len(doc.summary) == 1 and doc.summary[0].qty == 3.0


def test_integer_and_mark_positions_are_not_flagged() -> None:
    # Номера бывают целыми («1», «28») и кодами оборудования («М10.1», «ВК-1») — это нормально.
    data = _book(
        ["Поз.", "Наименование", "Ед.", "Кол"],
        [["1", "Стол", "шт.", 1], ["28", "Стул", "шт.", 2], ["М10.1", "Рециркулятор", "шт.", 1], ["ВК-1", "Ванна", "шт.", 1], ["?!", "Странная", "шт.", 1]],
    )
    doc = parse_xlsx(data, file_name="н.xlsx")
    flagged = [it.pos for it in doc.items if any("необычный номер" in w for w in it.warnings)]
    assert flagged == ["?!"]  # только по-настоящему странный номер


def test_dispatch_by_extension() -> None:
    assert is_supported("том.pdf") and is_supported("Спец.XLSX") and is_supported("с.xlsm")
    assert not is_supported("данные.csv") and not is_supported("рисунок.png")
    data = _book(["Поз.", "Наименование", "Ед.", "Кол-во"], [["1", "Стол", "шт.", 1]])
    doc = parse_document(data, file_name="спец.xlsx")
    assert len(doc.summary) == 1 and doc.summary[0].name == "Стол"
