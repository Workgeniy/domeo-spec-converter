"""Формирование Excel по образцу заказчика — приложения к договору со спецификацией и ценами.

С параметрами КП книга повторяет образец «Приложение 1.xlsx»: лист «1» — Приложение №1.1
(товар/оборудование, подлежащее монтажу/пусконаладке, с графами СМР), лист «2» — Приложение
№1.2 (инвентарь, не подлежащий монтажу). Без параметров — рабочая выгрузка: «Спецификация»
(та же форма 1.1, базовая цена как есть), «По помещениям» и «Проверка».
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from ..models import ExportRequest, KpSettings, SourceDocument, SpecItem, SummaryItem
from .kp import format_date, price_row

FONT = "Times New Roman"
THIN = Side(style="thin")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FILL_HEADER = PatternFill("solid", fgColor="D8D8D8")
FILL_SUPPLIER = PatternFill("solid", fgColor="95B3D7")
MONEY = "#,##0.00"
PERCENT = "0.00%"
VAT_RATE = 0.2
SIGN_LINE = "_______________________"


@dataclass(frozen=True)
class Appendix:
    """Форма приложения к договору: лист «1» (с монтажом) или «2» (без)."""

    number: str
    sheet: str
    subtitle: str
    columns: tuple[tuple[str, float], ...]
    with_installation: bool


# Графы и ширины столбцов — как в образце.
APPENDIX_1 = Appendix(
    number="1.1",
    sheet="1",
    subtitle="Спецификация на Товар/Оборудование, подлежащего монтажу/пусконаладке",
    columns=(
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
    ),
    with_installation=True,
)
APPENDIX_2 = Appendix(
    number="1.2",
    sheet="2",
    subtitle="Спецификация на Товар (инвентарь), не подлежащего монтажу/пусконаладке",
    columns=(
        ("№", 7.3),
        ("Раздел", 34.6),
        ("Наименование", 30.3),
        ("Технические характеристики", 60),
        ("Ед. изм.", 9.1),
        ("Кол во", 10.1),
        ("№ поз. в ТХ", 9.3),
        ("Цена за ед. без НДС", 13.1),
        ("Стоимость товара без НДС", 15),
        ("Ставка НДС", 9.3),
        ("Цена за ед. товара, с НДС", 13.1),
        ("Стоимость товара, с НДС", 19.3),
        ("Примечания Поставщика", 22.7),
    ),
    with_installation=False,
)

DETAIL_COLUMNS = [
    ("№", 5.6),
    ("Документ", 18),
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
    # Сквозная нумерация по всему своду, как в образце (№ не начинается заново на листе «2»).
    numbered = list(enumerate(data.summary, start=1))
    if data.kp is not None:
        mounted = [(n, s) for n, s in numbered if s.installation]
        inventory = [(n, s) for n, s in numbered if not s.installation]
        _fill_appendix(wb.active, data, mounted, data.kp, APPENDIX_1)
        _fill_appendix(wb.create_sheet(), data, inventory, data.kp, APPENDIX_2)
        return wb
    _fill_appendix(wb.active, data, numbered, None, APPENDIX_1, sheet_title="Спецификация")
    _fill_detail_sheet(wb.create_sheet("По помещениям"), data.items)
    _fill_check_sheet(wb.create_sheet("Проверка"), data)
    return wb


# ---------- приложения к договору (листы «1» и «2») ----------


def _fill_appendix(
    ws: Worksheet,
    data: ExportRequest,
    rows: list[tuple[int, SummaryItem]],
    kp: KpSettings | None,
    appendix: Appendix,
    sheet_title: str | None = None,
) -> None:
    ws.title = sheet_title or appendix.sheet
    last_col = len(appendix.columns)
    for idx, (_, width) in enumerate(appendix.columns, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    contract_no = (kp.contract_number if kp else "") or "___________"
    contract_date = format_date(kp.contract_date if kp else "", fallback="_____________г.")
    ws.merge_cells(start_row=1, start_column=2, end_row=1, end_column=last_col)
    ws.merge_cells(start_row=2, start_column=2, end_row=2, end_column=last_col)
    ws.cell(1, 2, f"Приложение №{appendix.number} к Договору № {contract_no} от {contract_date}")
    ws.cell(2, 2, appendix.subtitle)
    for row in (1, 2):
        ws.cell(row, 2).font = Font(name=FONT, size=12, bold=True)
        ws.cell(row, 2).alignment = Alignment(horizontal="right", vertical="center")
        ws.row_dimensions[row].height = 33

    for idx, (title, _) in enumerate(appendix.columns, start=1):
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
    for number, item in rows:
        if appendix.with_installation:
            _write_row_1(ws, row, number, item, kp)
        else:
            _write_row_2(ws, row, number, item, kp)
        _write_helper_columns(ws, row, last_col, kp, appendix.with_installation)
        row += 1
    last = max(row - 1, first)

    # Итог: на листе «1» — «Итого с НДС» в M/N, на листе «2» — «Всего с НДС» в K/L.
    total_col = last_col - 1
    label = ws.cell(row, total_col - 1, "Итого с НДС" if appendix.with_installation else "Всего с НДС")
    label.font = Font(name=FONT, size=10, bold=True)
    label.alignment = Alignment(horizontal="right", vertical="center")
    total_letter = get_column_letter(total_col)
    total = ws.cell(row, total_col, f"=SUM({total_letter}{first}:{total_letter}{last})")
    total.font = Font(name=FONT, size=10, bold=True)
    total.number_format = MONEY
    for col in (total_col - 1, total_col):
        ws.cell(row, col).border = BORDER
    total_row = row
    # Ссылка на итог в графах-подсказках за областью печати — как в образце (Q3 «=N162»).
    ws.cell(3, last_col + 2, f"={total_letter}{total_row}").number_format = MONEY
    for offset, title in enumerate(("пр", "дост", "монт"), start=3):
        ws.cell(3, last_col + offset, title).font = Font(name=FONT, size=10)

    # Как в образце: автофильтр на шапке и группировка строк таблицы (кнопки «1 2» слева).
    ws.auto_filter.ref = f"A3:{get_column_letter(last_col)}{max(last, first)}"
    if rows:
        ws.row_dimensions.group(first, last, outline_level=1)

    _write_signatures(ws, total_row + 2, kp)
    ws.freeze_panes = "A4"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f"A1:{get_column_letter(last_col)}{total_row + 10}"


def _write_row_1(ws: Worksheet, r: int, number: int, item: SummaryItem, kp: KpSettings | None) -> None:
    """Строка Приложения №1.1: графы H–N с СМР. Без параметров КП базовая цена идёт в M как есть."""
    installation: float | None = None
    unit_total: float | None = item.price
    if kp is not None and item.price is not None:
        p = price_row(item.price, kp, with_installation=True)
        installation = p.installation or None
        unit_total = p.unit_total
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
        installation,  # цена СМР за ед.; пусто — заполняет поставщик
        kp.vat_rate if kp is not None else VAT_RATE,
        unit_total,  # цена за ед. вкл. СМР, с НДС; пусто — заполняет поставщик
        f"=F{r}*M{r}",
        _supplier_note(item),
    ]
    _write_values(ws, r, values, money=(6, 8, 9, 10, 11, 13, 14), percent=12, text=(2, 3, 4, 15))
    _set_row_height(ws, r, item, APPENDIX_1)


def _write_row_2(ws: Worksheet, r: int, number: int, item: SummaryItem, kp: KpSettings | None) -> None:
    """Строка Приложения №1.2: без СМР, цена с НДС в K, без НДС — формулой в H."""
    sale: float | None = item.price
    if kp is not None and item.price is not None:
        sale = price_row(item.price, kp, with_installation=False).sale
    values: list[object] = [
        number,
        item.section,
        item.name,
        item.description,
        item.unit,
        item.qty,
        item.pos,
        f"=K{r}/(1+J{r})",
        f"=H{r}*F{r}",
        kp.vat_rate if kp is not None else VAT_RATE,
        sale,  # цена за ед. товара с НДС; пусто — заполняет поставщик
        f"=F{r}*K{r}",
        _supplier_note(item),
    ]
    _write_values(ws, r, values, money=(6, 8, 9, 11, 12), percent=10, text=(2, 3, 4, 13))
    _set_row_height(ws, r, item, APPENDIX_2)


def _write_values(ws: Worksheet, r: int, values: list[object], money: tuple[int, ...], percent: int, text: tuple[int, ...]) -> None:
    for idx, value in enumerate(values, start=1):
        cell = ws.cell(r, idx, value)
        cell.font = Font(name=FONT, size=10)
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="left" if idx in text else "center", vertical="center", wrap_text=True)
        if idx in money:
            cell.number_format = MONEY
        elif idx == percent:
            cell.number_format = PERCENT


def _write_helper_columns(ws: Worksheet, r: int, last_col: int, kp: KpSettings | None, with_installation: bool) -> None:
    """Графы «пр», «дост», «монт» за областью печати — проценты, по которым посчитана строка."""
    if kp is None:
        return
    values = (kp.markup_percent, kp.delivery_percent, kp.installation_percent if with_installation else 0)
    for offset, value in enumerate(values, start=3):
        ws.cell(r, last_col + offset, value).font = Font(name=FONT, size=10)


def _set_row_height(ws: Worksheet, r: int, item: SummaryItem, appendix: Appendix) -> None:
    ws.row_dimensions[r].height = _row_height(
        [
            (item.description, appendix.columns[3][1]),
            (item.name, appendix.columns[2][1]),
            (item.section, appendix.columns[1][1]),
        ]
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


def _write_signatures(ws: Worksheet, start: int, kp: KpSettings | None) -> None:
    """Блок подписей по образцу: «Подписи Сторон», через две строки «Заказчик:»/«Поставщик:»,
    ниже жирным должность, дальше только линии — организацию и подпись вписывают руками."""
    customer_position = (kp.customer_position if kp else "") or "Генеральный директор"
    supplier_position = (kp.supplier_position if kp else "") or "Генеральный директор"
    ws.cell(start, 1, "Подписи Сторон").font = Font(name=FONT, size=10, bold=True)
    lines = [
        (3, False, "Заказчик:", "Поставщик:"),
        (4, True, customer_position, supplier_position),
        (5, False, SIGN_LINE, SIGN_LINE),
        (7, False, SIGN_LINE + "/", SIGN_LINE + "/"),
    ]
    for offset, is_bold, left, right in lines:
        r = start + offset
        ws.cell(r, 2, left).font = Font(name=FONT, size=10, bold=is_bold)
        ws.merge_cells(start_row=r, start_column=6, end_row=r, end_column=10)
        ws.cell(r, 6, right).font = Font(name=FONT, size=10, bold=is_bold)
        ws.row_dimensions[r].height = 33


# ---------- лист «По помещениям» ----------


def _fill_detail_sheet(ws: Worksheet, items: list[SpecItem]) -> None:
    _write_header(ws, DETAIL_COLUMNS)
    for r, item in enumerate(items, start=2):
        values: list[object] = [
            r - 1,
            item.source_doc,
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
                horizontal="center" if idx in (1, 4, 9, 10, 12) else "left",
                vertical="center",
                wrap_text=True,
            )
        ws.row_dimensions[r].height = _row_height(
            [(item.description, DETAIL_COLUMNS[5][1]), (item.group, DETAIL_COLUMNS[2][1])]
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

    # Старые клиенты присылают только pages/warnings — тогда сводка по документу строится из них.
    documents = data.documents or [_legacy_source(data)]
    r = 1
    if data.title:
        ws.cell(r, 1, "Объект").font = bold
        ws.cell(r, 3, data.title).font = normal
        r += 1
    ws.cell(r, 1, "Строк в спецификации").font = bold
    ws.cell(r, 3, len(data.items)).font = normal
    ws.cell(r + 1, 1, "Позиций в своде").font = bold
    ws.cell(r + 1, 3, len(data.summary)).font = normal
    ws.cell(r + 2, 1, "Позиций с ценой").font = bold
    ws.cell(r + 2, 3, sum(1 for s in data.summary if s.price is not None)).font = normal
    r += 4

    for doc in documents:
        info = [
            ("Документ", doc.doc_code or doc.file_name),
            ("Файл", doc.file_name),
            ("Спецификация", doc.spec_title or "—"),
            ("Страниц в PDF", doc.pages_total),
            ("Страниц со спецификацией", ", ".join(map(str, doc.spec_pages)) or "—"),
            ("Страниц распознано OCR", ", ".join(map(str, doc.ocr_pages)) or "—"),
            ("Страниц пропущено (скан без OCR)", ", ".join(map(str, doc.skipped_pages)) or "—"),
            ("Строк / позиций", f"{doc.rows} / {doc.positions}"),
        ]
        for label, value in info:
            ws.cell(r, 1, label).font = bold if label == "Документ" else normal
            ws.cell(r, 3, value).font = bold if label == "Документ" else normal
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

    def where(doc: str, page: int | None = None) -> str:
        place = f"стр. {page}" if page else "документ"
        return f"{doc}, {place}" if doc else place

    rows: list[tuple[str, str, str]] = [(where(doc.doc_code), "", w) for doc in documents for w in doc.warnings]
    rows += [(where(i.source_doc, i.page), i.pos, w) for i in data.items for w in i.warnings]
    rows += [(f"свод{', ' + s.source_doc if s.source_doc else ''}", s.pos, w) for s in data.summary for w in s.warnings]
    if not rows:
        ws.cell(r, 1, "Замечаний нет").font = normal
    for where_, pos, text in rows:
        for idx, value in enumerate((where_, pos, text), start=1):
            cell = ws.cell(r, idx, value)
            cell.font = normal
            cell.border = BORDER
            cell.alignment = Alignment(vertical="center", wrap_text=idx == 3)
        r += 1


def _legacy_source(data: ExportRequest) -> SourceDocument:
    return SourceDocument(
        doc_code=data.doc_code,
        file_name=data.file_name,
        title=data.title,
        pages_total=len(data.pages),
        spec_pages=[p.number for p in data.pages if p.kind == "spec"],
        ocr_pages=[p.number for p in data.pages if p.source == "ocr"],
        skipped_pages=[p.number for p in data.pages if p.source == "skipped"],
        rows=len(data.items),
        positions=len(data.summary),
        warnings=list(data.warnings) + [f"стр. {p.number}: {w}" for p in data.pages for w in p.warnings],
    )


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
