"""Формирование Excel по образцу «Приложение №1.1 к Договору» (спецификация к КП).

Лист «Спецификация» повторяет форму образца: те же графы, формулы цен и итог.
Ценовые графы остаются пустыми — их заполняет менеджер (или следующие этапы),
формулы пересчитают стоимость сами. Дополнительно: лист «По помещениям» с
построчной раскладкой из PDF и лист «Проверка» с замечаниями разбора.
"""

from __future__ import annotations

import math

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from ..models import ExportRequest, SpecItem, SummaryItem

FONT = "Times New Roman"
THIN = Side(style="thin")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FILL_HEADER = PatternFill("solid", fgColor="D8D8D8")
FILL_SUPPLIER = PatternFill("solid", fgColor="95B3D7")
MONEY = "#,##0.00"
PERCENT = "0.00%"
VAT_RATE = 0.2

# Графы листа «Спецификация»: (заголовок, ширина столбца) — как в образце.
SPEC_COLUMNS = [
    ("№", 5.6),
    ("Раздел", 30),
    ("Наименование", 29.3),
    ("Технические характеристики", 54.3),
    ("Ед. изм.", 7.9),
    ("Кол во", 10.6),
    ("№ поз. в ТХ", 9),
    ("Цена за ед. без НДС", 15.1),
    ("Стоимость товара без НДС", 15.9),
    ("Цена за ед. товара, с НДС", 15.4),
    ("Цена за ед. СМР, с НДС", 14.4),
    ("Ставка НДС", 9),
    ("Цена за ед. товара (вкл. СМР), с НДС", 16.3),
    ("Стоимость ед. товара (вкл. СМР), с НДС", 15.7),
    ("Примечания Поставщика", 29.3),
]

DETAIL_COLUMNS = [
    ("№", 5.6),
    ("Помещение / раздел", 34),
    ("№ поз.", 9),
    ("Наименование", 29),
    ("Технические характеристики", 60),
    ("Тип, марка", 24),
    ("Завод-изготовитель", 20),
    ("Ед. изм.", 8),
    ("Кол-во", 8),
    ("Примечание", 30),
    ("Стр. PDF", 8),
    ("Замечания разбора", 36),
]


def build_workbook(data: ExportRequest) -> Workbook:
    wb = Workbook()
    _fill_spec_sheet(wb.active, data)
    _fill_detail_sheet(wb.create_sheet("По помещениям"), data.items)
    _fill_check_sheet(wb.create_sheet("Проверка"), data)
    return wb


# ---------- лист «Спецификация» ----------


def _fill_spec_sheet(ws: Worksheet, data: ExportRequest) -> None:
    ws.title = "Спецификация"
    last_col = len(SPEC_COLUMNS)
    for idx, (_, width) in enumerate(SPEC_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    ws.merge_cells(start_row=1, start_column=2, end_row=1, end_column=last_col)
    ws.merge_cells(start_row=2, start_column=2, end_row=2, end_column=last_col)
    ws.cell(1, 2, "Приложение №1.1 к Договору ___________ от _____________г.")
    ws.cell(2, 2, "Спецификация на Товар/Оборудование, подлежащего монтажу/пусконаладке")
    for row in (1, 2):
        ws.cell(row, 2).font = Font(name=FONT, size=12, bold=True)
        ws.cell(row, 2).alignment = Alignment(horizontal="right", vertical="center")
        ws.row_dimensions[row].height = 33

    for idx, (title, _) in enumerate(SPEC_COLUMNS, start=1):
        cell = ws.cell(3, idx, title)
        cell.font = Font(name=FONT, size=10, bold=idx > 1)
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        cell.border = BORDER
        if 2 <= idx <= 9:
            cell.fill = FILL_HEADER
        elif idx == last_col:
            cell.fill = FILL_SUPPLIER
    ws.row_dimensions[3].height = 45

    first = 4
    row = first
    for number, item in enumerate(data.summary, start=1):
        _write_spec_row(ws, row, number, item)
        row += 1
    last = row - 1

    if data.summary:
        total = ws.cell(row, 13, "Итого с НДС")
        total.font = Font(name=FONT, size=10, bold=True)
        total.alignment = Alignment(horizontal="right", vertical="center")
        sum_cell = ws.cell(row, 14, f"=SUM(N{first}:N{last})")
        sum_cell.font = Font(name=FONT, size=10, bold=True)
        sum_cell.number_format = MONEY
        for col in (13, 14):
            ws.cell(row, col).border = BORDER
        row += 1

    _write_signatures(ws, row + 2)
    ws.freeze_panes = "A4"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f"A1:{get_column_letter(last_col)}{row + 8}"


def _write_spec_row(ws: Worksheet, r: int, number: int, item: SummaryItem) -> None:
    values: list[object] = [
        number,
        item.section,
        item.name,
        item.description,
        item.unit,
        item.qty,
        item.pos,
        f"=J{r}/(1+L{r})",
        f"=H{r}*F{r}",
        f"=M{r}-K{r}",
        None,  # цена СМР — заполняет поставщик
        VAT_RATE,
        None,  # цена товара с СМР — заполняет поставщик
        f"=F{r}*M{r}",
        _supplier_note(item),
    ]
    for idx, value in enumerate(values, start=1):
        cell = ws.cell(r, idx, value)
        cell.font = Font(name=FONT, size=10)
        cell.border = BORDER
        cell.alignment = Alignment(
            horizontal="left" if idx in (2, 3, 4, 15) else "center",
            vertical="center",
            wrap_text=True,
        )
        if idx in (8, 9, 10, 11, 13, 14):
            cell.number_format = MONEY
        elif idx == 12:
            cell.number_format = PERCENT
    ws.row_dimensions[r].height = _row_height(
        [(item.description, SPEC_COLUMNS[3][1]), (item.name, SPEC_COLUMNS[2][1]), (item.section, SPEC_COLUMNS[1][1])]
    )


def _supplier_note(item: SummaryItem) -> str:
    parts = []
    if item.type_mark:
        parts.append(item.type_mark)
    if item.manufacturer and not item.manufacturer.lower().startswith("торговая сеть"):
        parts.append(item.manufacturer)
    if item.note:
        parts.append(item.note)
    return "; ".join(parts)


def _write_signatures(ws: Worksheet, start: int) -> None:
    ws.cell(start, 1, "Подписи Сторон").font = Font(name=FONT, size=10, bold=True)
    lines = [
        ("Заказчик:", "Поставщик:"),
        ("Генеральный директор", "Генеральный директор"),
        ("", ""),
        ("_______________________/", "_______________________/"),
    ]
    for offset, (left, right) in enumerate(lines, start=3):
        r = start + offset
        ws.cell(r, 2, left).font = Font(name=FONT, size=10)
        ws.merge_cells(start_row=r, start_column=6, end_row=r, end_column=12)
        ws.cell(r, 6, right).font = Font(name=FONT, size=10)


# ---------- лист «По помещениям» ----------


def _fill_detail_sheet(ws: Worksheet, items: list[SpecItem]) -> None:
    _write_header(ws, DETAIL_COLUMNS)
    for r, item in enumerate(items, start=2):
        values: list[object] = [
            r - 1,
            item.group,
            item.pos,
            item.name,
            item.description,
            item.type_mark,
            item.manufacturer,
            item.unit,
            item.qty if item.qty is not None else item.qty_raw,
            item.note,
            item.page,
            "; ".join(item.warnings),
        ]
        for idx, value in enumerate(values, start=1):
            cell = ws.cell(r, idx, value)
            cell.font = Font(name=FONT, size=10)
            cell.border = BORDER
            cell.alignment = Alignment(
                horizontal="center" if idx in (1, 3, 8, 9, 11) else "left",
                vertical="center",
                wrap_text=True,
            )
        ws.row_dimensions[r].height = _row_height(
            [(item.description, DETAIL_COLUMNS[4][1]), (item.group, DETAIL_COLUMNS[1][1])]
        )
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(DETAIL_COLUMNS))}{max(len(items) + 1, 2)}"


# ---------- лист «Проверка» ----------


def _fill_check_sheet(ws: Worksheet, data: ExportRequest) -> None:
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 90
    bold = Font(name=FONT, size=10, bold=True)
    normal = Font(name=FONT, size=10)

    spec_pages = [p for p in data.pages if p.kind == "spec"]
    ocr_pages = [p for p in data.pages if p.source == "ocr"]
    skipped = [p for p in data.pages if p.source == "skipped"]
    info = [
        ("Файл", data.file_name),
        ("Шифр документа", data.doc_code),
        ("Объект", data.title),
        ("Страниц в PDF", len(data.pages)),
        ("Страниц со спецификацией", ", ".join(str(p.number) for p in spec_pages)),
        ("Страниц распознано OCR", ", ".join(str(p.number) for p in ocr_pages) or "—"),
        ("Страниц пропущено (скан без OCR)", ", ".join(str(p.number) for p in skipped) or "—"),
        ("Строк в спецификации", len(data.items)),
        ("Позиций в своде", len(data.summary)),
    ]
    r = 1
    for label, value in info:
        ws.cell(r, 1, label).font = bold
        ws.cell(r, 3, value).font = normal
        r += 1

    r += 1
    ws.cell(r, 1, "Замечания").font = bold
    r += 1
    for idx, title in enumerate(("Где", "Позиция", "Замечание"), start=1):
        cell = ws.cell(r, idx, title)
        cell.font = bold
        cell.fill = FILL_HEADER
        cell.border = BORDER
    r += 1

    rows: list[tuple[str, str, str]] = [("документ", "", w) for w in data.warnings]
    rows += [(f"стр. {p.number}", "", w) for p in data.pages for w in p.warnings]
    rows += [(f"стр. {i.page}", i.pos, w) for i in data.items for w in i.warnings]
    rows += [("свод", s.pos, w) for s in data.summary for w in s.warnings]
    if not rows:
        ws.cell(r, 1, "Замечаний нет").font = normal
    for where, pos, text in rows:
        for idx, value in enumerate((where, pos, text), start=1):
            cell = ws.cell(r, idx, value)
            cell.font = normal
            cell.border = BORDER
            cell.alignment = Alignment(vertical="center", wrap_text=idx == 3)
        r += 1


# ---------- общее ----------


def _write_header(ws: Worksheet, columns: list[tuple[str, float]]) -> None:
    for idx, (title, width) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
        cell = ws.cell(1, idx, title)
        cell.font = Font(name=FONT, size=10, bold=True)
        cell.fill = FILL_HEADER
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 32


def _row_height(texts: list[tuple[str, float]], line_height: float = 13.0, min_height: float = 18.0) -> float:
    """Оценка высоты строки по самому длинному тексту с учётом ширины столбца.

    Excel не пересчитывает высоту строк при открытии файла, созданного
    программно, поэтому высоту приходится задавать самим.
    """
    lines = 1
    for text, width in texts:
        if not text:
            continue
        chars_per_line = max(int(width * 1.1), 10)
        lines = max(lines, sum(max(1, math.ceil(len(part) / chars_per_line)) for part in text.split("\n")))
    return max(min_height, min(lines * line_height + 4, 400))
