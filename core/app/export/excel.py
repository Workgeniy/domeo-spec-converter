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

from ..models import ExportRequest, KpSettings, Party, SourceDocument, SpecItem, SummaryItem
from .kp import format_date, price_row, valid_until

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
    _fill_spec_sheet(wb.active, data)
    if data.kp is not None:
        # Лист «КП» — первым: это титул предложения, спецификация — его приложение.
        _fill_kp_sheet(wb.create_sheet("КП", 0), data, data.kp)
    _fill_detail_sheet(wb.create_sheet("По помещениям"), data.items)
    _fill_check_sheet(wb.create_sheet("Проверка"), data)
    return wb


# ---------- лист «Спецификация» ----------


def _fill_spec_sheet(ws: Worksheet, data: ExportRequest) -> None:
    ws.title = "Спецификация"
    last_col = len(SPEC_COLUMNS)
    for idx, (_, width) in enumerate(SPEC_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    kp = data.kp
    contract_no = (kp.contract_number if kp else "") or "___________"
    contract_date = format_date(kp.contract_date if kp else "", fallback="_____________г.")
    ws.merge_cells(start_row=1, start_column=2, end_row=1, end_column=last_col)
    ws.merge_cells(start_row=2, start_column=2, end_row=2, end_column=last_col)
    ws.cell(1, 2, f"Приложение №1.1 к Договору № {contract_no} от {contract_date}")
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
        _write_spec_row(ws, row, number, item, kp)
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

    _write_signatures(ws, row + 2, kp)
    ws.freeze_panes = "A4"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f"A1:{get_column_letter(last_col)}{row + 8}"


def _write_spec_row(ws: Worksheet, r: int, number: int, item: SummaryItem, kp: KpSettings | None) -> None:
    # Без параметров КП базовая цена идёт в графу M как есть; с параметрами — через правила
    # kp.price_row (наценка → J, СМР → K, сумма → M).
    installation: float | None = None
    unit_total: float | None = item.price
    if kp is not None and item.price is not None:
        p = price_row(item.price, kp)
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


def _write_signatures(ws: Worksheet, start: int, kp: KpSettings | None) -> None:
    customer = kp.customer if kp else Party()
    supplier = kp.supplier if kp else Party()
    ws.cell(start, 1, "Подписи Сторон").font = Font(name=FONT, size=10, bold=True)
    lines = [
        ("Заказчик:", "Поставщик:"),
        (customer.director or "Генеральный директор", supplier.director or "Генеральный директор"),
        (customer.name, supplier.name),
        ("_______________________/", "_______________________/"),
    ]
    for offset, (left, right) in enumerate(lines, start=3):
        r = start + offset
        ws.cell(r, 2, left).font = Font(name=FONT, size=10)
        ws.merge_cells(start_row=r, start_column=6, end_row=r, end_column=12)
        ws.cell(r, 6, right).font = Font(name=FONT, size=10)


# ---------- лист «КП» ----------

KP_SECTION_COLUMNS = [
    ("№", 5),
    ("Раздел", 46),
    ("Позиций", 9),
    ("Стоимость товара без НДС", 20),
    ("НДС", 16),
    ("Стоимость товара с НДС", 20),
    ("СМР с НДС", 16),
    ("Итого с НДС", 20),
]


def _fill_kp_sheet(ws: Worksheet, data: ExportRequest, kp: KpSettings) -> None:
    """Титул предложения: реквизиты, итоги по разделам и общие, условия, подписи.

    Все суммы — формулами на лист «Спецификация», чтобы правка цены в Excel пересчитывала КП.
    """
    for idx, (_, width) in enumerate(KP_SECTION_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    bold = Font(name=FONT, size=10, bold=True)
    normal = Font(name=FONT, size=10)
    last_col = len(KP_SECTION_COLUMNS)

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    title = ws.cell(1, 1, f"КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ № {kp.number or '____'} от {format_date(kp.date)}")
    title.font = Font(name=FONT, size=14, bold=True)
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    codes = ", ".join(d.doc_code for d in data.documents if d.doc_code) or data.doc_code
    until = valid_until(kp)
    info = [
        ("Поставщик", _party_line(kp.supplier)),
        ("Заказчик", _party_line(kp.customer)),
        ("Объект", data.title),
        ("Основание", f"спецификации технологического оборудования {codes}" if codes else "спецификация технологического оборудования"),
        ("Действительно до", until or "—"),
        (
            "Условия расчёта",
            f"НДС {kp.vat_rate:.0%}; наценка {kp.markup_percent:g} %; СМР {kp.installation_percent:g} % от цены товара; "
            f"доставка {kp.delivery_percent:g} % от стоимости товара; цены {'до рубля' if kp.round_to_ruble else 'до копейки'}",
        ),
    ]
    r = 3
    for label, value in info:
        ws.cell(r, 1, label).font = bold
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=last_col)
        cell = ws.cell(r, 2, value)
        cell.font = normal
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        r += 1

    r += 1
    ws.cell(r, 1, "Состав предложения").font = bold
    r += 1
    for idx, (label, _) in enumerate(KP_SECTION_COLUMNS, start=1):
        cell = ws.cell(r, idx, label)
        cell.font = bold
        cell.fill = FILL_HEADER
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[r].height = 32
    r += 1

    first, last = 4, 3 + max(len(data.summary), 1)
    rng = lambda col: f"'Спецификация'!${col}${first}:${col}${last}"  # noqa: E731
    sections = list(dict.fromkeys(item.section for item in data.summary))
    table_first = r
    for number, section in enumerate(sections, start=1):
        crit = '"' + section.replace('"', '""') + '"'
        match = f"({rng('B')}={crit})"
        values: list[object] = [
            number,
            section or "Без раздела",
            f"=COUNTIF({rng('B')},{crit})",
            f"=SUMIF({rng('B')},{crit},{rng('I')})",
            f"=F{r}-D{r}",
            f"=SUMPRODUCT({match}*{rng('F')}*{rng('J')})",
            f"=SUMPRODUCT({match}*{rng('F')}*{rng('K')})",
            f"=SUMIF({rng('B')},{crit},{rng('N')})",
        ]
        _write_kp_row(ws, r, values, normal)
        r += 1
    table_last = r - 1

    def col_sum(col: str) -> str:
        return f"=SUM({col}{table_first}:{col}{table_last})" if sections else "=0"

    _write_kp_row(ws, r, ["", "Итого по товару и СМР", col_sum("C"), col_sum("D"), col_sum("E"), col_sum("F"), col_sum("G"), col_sum("H")], bold)
    goods_row, r = r, r + 1
    _write_kp_row(ws, r, ["", f"Доставка ({kp.delivery_percent:g} % от стоимости товара с НДС)", "", "", "", "", "", f"=ROUND(F{goods_row}*{kp.delivery_percent}/100,2)"], normal)
    delivery_row, r = r, r + 1
    _write_kp_row(ws, r, ["", "ИТОГО ПО ПРЕДЛОЖЕНИЮ, с НДС", "", "", "", "", "", f"=H{goods_row}+H{delivery_row}"], bold)
    ws.cell(r, 8).font = Font(name=FONT, size=11, bold=True)
    r += 2

    if kp.terms:
        ws.cell(r, 1, "Условия").font = bold
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=last_col)
        cell = ws.cell(r, 2, kp.terms)
        cell.font = normal
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = _row_height([(kp.terms, 120)])
        r += 2

    unpriced = sum(1 for item in data.summary if item.price is None)
    if unpriced:
        cell = ws.cell(r, 1, f"Внимание: у {unpriced} позиций из {len(data.summary)} нет цены — в итоги они не вошли.")
        cell.font = Font(name=FONT, size=10, bold=True, color="C00000")
        r += 2

    ws.cell(r, 1, "Поставщик:").font = bold
    ws.cell(r, 2, f"{kp.supplier.director or 'Генеральный директор'} {kp.supplier.name}".strip()).font = normal
    ws.cell(r + 1, 2, "_______________________/").font = normal
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def _party_line(party: Party) -> str:
    return ", ".join(p for p in (party.name, party.director, party.contacts) if p) or "—"


def _write_kp_row(ws: Worksheet, r: int, values: list[object], font: Font) -> None:
    for idx, value in enumerate(values, start=1):
        cell = ws.cell(r, idx, value if value != "" else None)
        cell.font = font
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="left" if idx == 2 else "center", vertical="center", wrap_text=True)
        if idx >= 4:
            cell.number_format = MONEY


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
    for where, pos, text in rows:
        for idx, value in enumerate((where, pos, text), start=1):
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
