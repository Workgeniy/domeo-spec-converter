"""Формирование Excel по образцу заказчика — приложения к договору со спецификацией и ценами.

С параметрами КП книга повторяет образец «Приложение 1.xlsx»: лист «1» — Приложение №1.1
(товар/оборудование, подлежащее монтажу/пусконаладке, с графами СМР), лист «2» — Приложение
№1.2 (инвентарь, не подлежащий монтажу). Без параметров — рабочая выгрузка: «Спецификация»
(та же форма 1.1, базовая цена как есть), «По помещениям» и «Проверка».
"""

from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass
from datetime import date

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from ..models import ExportRequest, KpSettings, SourceDocument, SpecItem, SummaryItem
from ..parsing.aggregate import cross_volume_duplicates
from ..pricing.attributes import parse_params
from ..pricing.indexation import indexation_factor, rate_for, years_between
from .kp import effective_markup, format_date, price_row, round_half_up

FONT = "Times New Roman"
THIN = Side(style="thin")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FILL_HEADER = PatternFill("solid", fgColor="D8D8D8")
FILL_SUPPLIER = PatternFill("solid", fgColor="95B3D7")
MONEY = "#,##0.00"
PERCENT = "0.00%"
VAT_RATE = 0.22  # запасная ставка НДС, если КП без настроек (рабочая выгрузка)
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
    kind = data.resolved_kind()
    # Сквозная нумерация по всему своду, как в образце (№ не начинается заново на листе «2»).
    numbered = list(enumerate(data.summary, start=1))
    if kind == "kp" and data.kp is not None:
        if data.kp_template:
            from .template import build_template_workbook

            return build_template_workbook(data)
        delivery = _indexation_date(data)
        if delivery is not None and data.indexation is not None and data.indexation.apply_to_kp:
            # КП на будущую поставку: базовая цена каждой строки проиндексирована к дате по ставке раздела.
            numbered = [(n, _indexed_item(s, data.indexation.rates, delivery, date.fromisoformat(data.indexation.base_date) if data.indexation.base_date else None)) for n, s in numbered]
        mounted = [(n, s) for n, s in numbered if s.installation]
        inventory = [(n, s) for n, s in numbered if not s.installation]
        _fill_appendix(wb.active, data, mounted, data.kp, APPENDIX_1)
        _fill_appendix(wb.create_sheet(), data, inventory, data.kp, APPENDIX_2)
        return wb
    if kind == "cost":
        _fill_cost_sheet(wb.active, data, numbered)
        _fill_history_sheet(wb.create_sheet("Покупки по истории"), numbered)
        if any(item.internet for _, item in numbered):
            _fill_internet_sheet(wb.create_sheet("Предложения из интернета"), numbered)
        return wb
    _fill_appendix(wb.active, data, numbered, None, APPENDIX_1, sheet_title="Спецификация")
    _fill_detail_sheet(wb.create_sheet("По помещениям"), data.items)
    _fill_check_sheet(wb.create_sheet("Проверка"), data)
    return wb


# ---------- себестоимость для Домео ----------

COST_COLUMNS = [
    ("№", 5.6),
    ("Раздел", 26),
    ("Наименование", 30),
    ("Технические характеристики", 50),
    ("Ед. изм.", 8),
    ("Кол во", 9),
    ("№ поз. в ТХ", 9),
    ("Цена интернет на дату", 14),
    ("Дата / источник", 16),
    ("Цена минимальная по истории закупок", 15),
    ("Цена максимальная по истории закупок", 15),
    ("Последняя закупка", 13),
    ("Дата последней", 12),
    ("Сопоставление с историей", 34),
    ("Выбранная цена, с НДС", 14),
    ("Откуда", 13),
    ("Стоимость, с НДС", 15),
]
PRICE_SOURCE_LABELS = {
    "": "",
    "manual": "вручную",
    "history_min": "мин. история",
    "history_max": "макс. история",
    "history_median": "медиана история",
    "history_last": "последняя закупка",
    "internet": "интернет",
}
MATCH_KIND_LABELS = {"exact": "точно", "fuzzy": "похоже", "analog": "аналог", "none": "не найдено"}


def _indexation_date(data: ExportRequest) -> date | None:
    if data.indexation is None or not data.indexation.date:
        return None
    try:
        return date.fromisoformat(data.indexation.date)
    except ValueError:
        return None


def _indexed_item(item: SummaryItem, rates: dict[str, float], delivery: date, start: date | None = None) -> SummaryItem:
    rate = rate_for(item.section, rates)
    if item.price is None or rate is None:
        return item
    return item.model_copy(update={"price": round_half_up(item.price * indexation_factor(rate, start or date.today(), delivery), 2)})


def _fill_cost_sheet(ws: Worksheet, data: ExportRequest, rows: list[tuple[int, SummaryItem]]) -> None:
    """Файл себестоимости: три цены на позицию (интернет / мин / макс по истории) и выбор оператора;
    с датой поставки — ещё ставка индексации раздела и цена к дате (формулами, чтобы ставку
    можно было поправить прямо в Excel)."""
    ws.title = "Себестоимость"
    delivery = _indexation_date(data)
    years = years_between(date.fromisoformat(data.indexation.base_date) if data.indexation and data.indexation.base_date else date.today(), delivery) if delivery is not None else 0.0
    columns = list(COST_COLUMNS)
    if delivery is not None:
        columns += [("Индексация, % в год", 12), (f"Цена на {delivery.isoformat()}", 14), (f"Стоимость на {delivery.isoformat()}", 15)]
    last_col = len(columns)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    title_text = f"Себестоимость: {data.title or data.doc_code}".strip(": ")
    if delivery is not None:
        title_text += f" (цены проиндексированы к {delivery.isoformat()}, {years:.2f} г.)"
    title = ws.cell(1, 1, title_text)
    title.font = Font(name=FONT, size=12, bold=True)
    ws.row_dimensions[1].height = 24
    for idx, (label, width) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
        cell = ws.cell(2, idx, label)
        cell.font = Font(name=FONT, size=10, bold=True)
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.fill = FILL_SUPPLIER if 8 <= idx <= 13 else FILL_HEADER
    ws.row_dimensions[2].height = 58

    first = 3
    r = first
    for number, item in rows:
        h = item.history
        best = h.best if h else None
        match_text = ""
        if h and best:
            match_text = f"{MATCH_KIND_LABELS.get(h.kind, h.kind)}: {best.name} ({best.purchases} закуп.)"
        elif h:
            match_text = MATCH_KIND_LABELS["none"]
        values: list[object] = [
            number,
            item.section,
            item.name,
            item.description,
            item.unit,
            item.qty,
            item.pos,
            item.internet_price,
            " ".join(p for p in (item.internet_date, item.internet_source) if p),
            best.price_min if best else None,
            best.price_max if best else None,
            best.price_last if best else None,
            best.last_date if best else None,
            match_text,
            item.price,
            PRICE_SOURCE_LABELS.get(item.price_source, item.price_source),
            f"=F{r}*O{r}",
        ]
        money: tuple[int, ...] = (6, 8, 10, 11, 12, 15, 17)
        if delivery is not None:
            rate = rate_for(item.section, data.indexation.rates) if data.indexation is not None else None
            can_index = rate is not None and item.price is not None
            values += [rate, f"=ROUND(O{r}*(1+R{r}/100)^{years:.4f},2)" if can_index else None, f"=F{r}*S{r}" if can_index else None]
            money += (19, 20)
        _write_values(ws, r, values, money=money, percent=0, text=(2, 3, 4, 9, 14, 16))
        if h and h.kind == "analog":
            ws.cell(r, 14).font = Font(name=FONT, size=10, color="C00000")  # аналог — оператор должен проверить
        if item.internet_source.startswith("http"):
            # Вместо длинной ссылки — дата и продавец, сама ссылка — гиперссылкой.
            offer = next((o for o in (item.internet.offers if item.internet else []) if o.url == item.internet_source), None)
            source = ws.cell(r, 9)
            source.value = " · ".join(p for p in (item.internet_date, offer.shop if offer else "ссылка") if p)
            source.hyperlink = item.internet_source
            source.font = Font(name=FONT, size=10, color="0563C1", underline="single")
        ws.row_dimensions[r].height = _row_height([(item.description, COST_COLUMNS[3][1]), (match_text, COST_COLUMNS[13][1])])
        r += 1
    last = max(r - 1, first)
    label = ws.cell(r, 16, "Итого, с НДС")
    label.font = Font(name=FONT, size=10, bold=True)
    total = ws.cell(r, 17, f"=SUM(Q{first}:Q{last})")
    total.font = Font(name=FONT, size=10, bold=True)
    total.number_format = MONEY
    for col in (16, 17):
        ws.cell(r, col).border = BORDER
    if delivery is not None:
        label_dated = ws.cell(r, 19, f"Итого на {delivery.isoformat()}")
        label_dated.font = Font(name=FONT, size=10, bold=True)
        total_dated = ws.cell(r, 20, f"=SUM(T{first}:T{last})")
        total_dated.font = Font(name=FONT, size=10, bold=True)
        total_dated.number_format = MONEY
        for col in (19, 20):
            ws.cell(r, col).border = BORDER
    r += 2
    priced = sum(1 for _, s in rows if s.price is not None)
    ws.cell(r, 1, f"Позиций: {len(rows)}; с выбранной ценой: {priced}; без цены: {len(rows) - priced}.").font = Font(name=FONT, size=10)
    ws.auto_filter.ref = f"A2:{get_column_letter(last_col)}{last}"
    ws.freeze_panes = "D3"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


HISTORY_COLUMNS = [("№", 5.6), ("№ поз. в ТХ", 10), ("Позиция", 34), ("Найдено в истории", 34), ("Дата", 11), ("Цена за ед.", 13), ("Кол-во", 8), ("Что купили", 44), ("Заказ", 30), ("Примечание", 12)]


def _fill_history_sheet(ws: Worksheet, rows: list[tuple[int, SummaryItem]]) -> None:
    """Последние покупки по каждой сопоставленной позиции — чтобы видеть, откуда эталоны."""
    _write_header(ws, HISTORY_COLUMNS)
    r = 2
    for number, item in rows:
        h = item.history
        if not h or not h.best:
            continue
        for p in h.purchases:
            values: list[object] = [number, item.pos, item.name, h.best.name, p.purchased_at, p.unit_price, p.qty, p.partner_item, p.order, "выброс" if p.outlier else ""]
            for idx, value in enumerate(values, start=1):
                cell = ws.cell(r, idx, value)
                cell.font = Font(name=FONT, size=10, color="808080" if p.outlier else None)
                cell.border = BORDER
                cell.alignment = Alignment(horizontal="center" if idx in (1, 2, 5, 6, 7) else "left", vertical="center", wrap_text=True)
                if idx == 6:
                    cell.number_format = MONEY
            r += 1
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(HISTORY_COLUMNS))}{max(r - 1, 2)}"


INTERNET_COLUMNS = [("№", 5.6), ("№ поз. в ТХ", 10), ("Позиция", 34), ("Дата", 11), ("Продавец", 20), ("Предложение", 44), ("Цена", 13), ("Аналог", 8), ("Ссылка", 50), ("Примечание", 34)]


def _fill_internet_sheet(ws: Worksheet, rows: list[tuple[int, SummaryItem]]) -> None:
    """Все найденные в интернете предложения по каждой позиции — откуда взялась цена на дату."""
    _write_header(ws, INTERNET_COLUMNS)
    r = 2

    def put(values: list[object], *, dim: bool = False) -> None:
        nonlocal r
        for idx, value in enumerate(values, start=1):
            cell = ws.cell(r, idx, value)
            cell.font = Font(name=FONT, size=10, color="808080" if dim else None)
            cell.border = BORDER
            cell.alignment = Alignment(horizontal="center" if idx in (1, 2, 4, 7, 8) else "left", vertical="center", wrap_text=True)
            if idx == 7:
                cell.number_format = MONEY
            if idx == 9 and isinstance(value, str) and value.startswith("http"):
                cell.hyperlink = value
                cell.font = Font(name=FONT, size=10, color="0563C1", underline="single")
        r += 1

    for number, item in rows:
        lookup = item.internet
        if not lookup:
            continue
        searched = parse_params(lookup.params or item.search_params)
        if not searched.empty():
            put([number, item.pos, item.name, lookup.looked_up_at, "", f"Параметры поиска: {searched.describe()}", None, "", "", ""], dim=True)
        if not lookup.offers:
            note = lookup.comment if lookup.status == "not_found" else f"ошибка: {lookup.comment}"
            put([number, item.pos, item.name, lookup.looked_up_at, "", "не найдено" if lookup.status == "not_found" else "не удалось найти", None, "", "", note], dim=True)
            continue
        for offer in lookup.offers:
            put([number, item.pos, item.name, lookup.looked_up_at, offer.shop, offer.title, offer.price, "да" if offer.analog else "", offer.url, offer.note])
        if lookup.comment:
            put([number, item.pos, item.name, lookup.looked_up_at, "", f"Комментарий: {lookup.comment}", None, "", "", ""], dim=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(INTERNET_COLUMNS))}{max(r - 1, 2)}"


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
    has_images = any(item.image for _number, item in rows)
    if has_images:
        _add_appendix_images(ws, rows, last_col, first)

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
    ws.print_area = f"A1:{get_column_letter(last_col + (1 if has_images else 0))}{total_row + 10}"


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
    values = (effective_markup(kp), kp.delivery_percent, kp.installation_percent if with_installation else 0)
    for offset, value in enumerate(values, start=3):
        ws.cell(r, last_col + offset, value).font = Font(name=FONT, size=10)


IMAGE_CELL_PX = 96  # размер картинки товара в ячейке приложения КП


def _cell_image(data_uri: str, max_px: int = IMAGE_CELL_PX) -> XLImage | None:
    """Картинка из data-URI → объект для вставки в Excel, вписанная в max_px. None — если нет/битая."""
    if not data_uri or "," not in data_uri:
        return None
    try:
        raw = base64.b64decode(data_uri.split(",", 1)[1])
        pic = XLImage(io.BytesIO(raw))
        w, h = pic.width or max_px, pic.height or max_px
        scale = min(max_px / w, max_px / h, 1.0)
        pic.width, pic.height = int(w * scale), int(h * scale)
        return pic
    except Exception:  # noqa: BLE001 — картинка не критична для выгрузки
        return None


def _add_appendix_images(ws: Worksheet, rows: list[tuple[int, SummaryItem]], last_col: int, first: int) -> None:
    """Столбец «Изображение» после основных граф приложения: миниатюра товара в каждой строке."""
    col = last_col + 1
    ws.column_dimensions[get_column_letter(col)].width = 15.5
    header = ws.cell(3, col, "Изображение")
    header.font = Font(name=FONT, size=10, bold=True)
    header.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    header.border = BORDER
    header.fill = FILL_SUPPLIER
    for offset, (_number, item) in enumerate(rows):
        r = first + offset
        ws.cell(r, col).border = BORDER
        pic = _cell_image(item.image)
        if pic is None:
            continue
        ws.add_image(pic, f"{get_column_letter(col)}{r}")
        need = pic.height * 0.75 + 6  # пиксели → пункты высоты строки
        if (ws.row_dimensions[r].height or 0) < need:
            ws.row_dimensions[r].height = need


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

    duplicates = cross_volume_duplicates(data.summary) if len(documents) > 1 else []
    if duplicates:
        ws.cell(r, 1, "Совпадающие позиции между томами").font = bold
        r += 1
        ws.cell(r, 3, "Одно наименование встречается в нескольких томах — проверьте, не задвоено ли количество; лишнее исключите из КП.").font = normal
        r += 1
        for group in duplicates:
            parts = ", ".join(f"{_dup_place(s)} — {_fmt_qty(s.qty)}" for s in group)
            name = group[0].description or group[0].name
            for idx, value in enumerate(("между томами", "", f"«{name[:200]}»: {parts}"), start=1):
                cell = ws.cell(r, idx, value)
                cell.font = normal
                cell.fill = FILL_SUPPLIER
                cell.border = BORDER
                cell.alignment = Alignment(vertical="center", wrap_text=idx == 3)
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


def _dup_place(item: SummaryItem) -> str:
    """«ТХ2, поз. 7.48» — где именно встретилась совпавшая позиция."""
    place = f"поз. {item.pos}" if item.pos else "без номера"
    return f"{item.source_doc}, {place}" if item.source_doc else place


def _fmt_qty(qty: float | None) -> str:
    if qty is None:
        return "кол-во не указано"
    return f"{int(qty) if float(qty).is_integer() else qty} шт."


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
