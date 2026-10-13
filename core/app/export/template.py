"""Заполнение выбранной формы КП с сохранением оформления исходной книги."""

from __future__ import annotations

from .kp import effective_markup

import base64
import binascii
import io
import re
import zipfile
from copy import copy
from collections import defaultdict

from openpyxl import Workbook, load_workbook
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter

from ..models import ExportRequest
from .kp import format_date, round_half_up


def _key(value: object) -> str:
    return re.sub(r"[^а-яa-z0-9]", "", str(value or "").lower().replace("ё", "е"))


def _layout(ws):
    from .excel import APPENDIX_1, APPENDIX_2

    labels = {_key(label): label for form in (APPENDIX_1, APPENDIX_2) for label, _ in form.columns}
    aliases = {"количество": "Кол во", "колво": "Кол во", "единицаизмерения": "Ед. изм.",
               "наименованиетовара": "Наименование", "ценасндс": "Цена за ед. товара, с НДС"}
    for row in ws.iter_rows(max_row=min(ws.max_row, 60)):
        columns = {}
        for cell in row:
            label = aliases.get(_key(cell.value), labels.get(_key(cell.value)))
            if label:
                columns[label] = cell.column
        if {"Наименование", "Кол во"} <= columns.keys():
            if not ({"Цена за ед. товара, с НДС", "Цена за ед. товара (вкл. СМР), с НДС"} & columns.keys()):
                # Детализация по помещениям и другие вспомогательные листы сохраняются,
                # но не являются формой КП и не должны блокировать заполнение основной.
                continue
            for cells in ws.iter_rows(min_row=row[0].row + 1, max_row=ws.max_row):
                r = cells[0].row
                if any(isinstance(c.value, str) and re.match(r"^(итого|всего)\b", c.value.strip(), re.I)
                       for c in cells):
                    if r <= row[0].row + 1:
                        raise ValueError("Шаблон: оставьте хотя бы одну строку-образец между шапкой и итогом.")
                    return row[0].row, r, columns
            raise ValueError(f"Шаблон: на листе «{ws.title}» нужна строка «Итого» или «Всего» после таблицы.")
    return None


def _formula(value, origin, destination):
    if isinstance(value, str) and value.startswith("="):
        return Translator(value, origin=origin).translate_formula(destination)
    return value


def build_template_workbook(data: ExportRequest) -> Workbook:
    from .excel import build_workbook

    try:
        raw = base64.b64decode(data.kp_template, validate=True)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > 50_000_000:
                raise ValueError("Шаблон слишком большой после распаковки (максимум 50 МБ).")
        wb = load_workbook(io.BytesIO(raw))
    except (binascii.Error, zipfile.BadZipFile, KeyError, OSError) as exc:
        raise ValueError("Не удалось прочитать шаблон. Выберите корректный файл XLSX.") from exc
    layouts = [(ws, layout) for ws in wb if (layout := _layout(ws)) is not None]
    if not layouts or len(layouts) > 2:
        raise ValueError("Шаблон должен содержать одну или две таблицы КП с заголовками «Наименование», «Кол во» и ценой с НДС.")
    mounted = lambda columns: bool({"Цена за ед. СМР, с НДС", "Цена за ед. товара (вкл. СМР), с НДС"} & columns.keys())
    if len(layouts) == 2 and mounted(layouts[0][1][2]) == mounted(layouts[1][1][2]):
        raise ValueError("В шаблоне с двумя таблицами одна должна содержать графу СМР, другая — быть без монтажа.")
    generated = build_workbook(data.model_copy(update={"kp_template": None})) if len(layouts) == 2 else None
    for ws, (header, old_total, columns) in layouts:
        with_installation = mounted(columns)
        if len(layouts) == 1:
            # Одна таблица: все позиции в исходном порядке, монтаж только у отмеченных строк.
            # Одна промежуточная книга на весь свод: не создаём тысячи книг по одной строке.
            single = build_workbook(data.model_copy(update={"summary": [item.model_copy(update={"installation": with_installation})
                for item in data.summary], "kp_template": None}))
            source = single["1" if with_installation else "2"]
            digits = 0 if data.kp.round_to_ruble else 2
            for r, item in enumerate(data.summary, 4):
                if item.price is None:
                    continue
                if with_installation and not item.installation:
                    source.cell(r, 13).value = round_half_up(source.cell(r, 13).value - (source.cell(r, 11).value or 0), digits)
                    source.cell(r, 11).value = None
                elif not with_installation and item.installation:
                    sale = source.cell(r, 11).value
                    installation = round_half_up(sale * data.kp.installation_percent / 100, digits)
                    source.cell(r, 11).value = round_half_up(sale + installation, digits)
            sources = [(source, r) for r in range(4, 4 + len(data.summary))]
        else:
            source = generated["1" if with_installation else "2"]
            count = sum(item.installation == with_installation for item in data.summary)
            sources = [(source, r) for r in range(4, 4 + count)]
        _fill(ws, header, old_total, columns, sources, data, len(layouts) == 1)
    return wb


def _fill(ws, header, old_total, columns, sources, data, renumber):
    first = header + 1
    count = max(1, len(sources))
    new_total = first + count
    delta = new_total - old_total
    # Снимок ячеек и размеров позволяет перенести весь подвал, включая подписи и объединения.
    cells = defaultdict(list)
    for row in ws:
        for cell in row:
            if cell.__class__.__name__ != "MergedCell":
                cells[cell.row].append(copy(cell))
    dimensions = {r: copy(d) for r, d in ws.row_dimensions.items()}
    merges = list(ws.merged_cells.ranges)
    if any(m.min_row < old_total and m.max_row >= first for m in merges):
        raise ValueError(f"Шаблон: объединения внутри строк товаров на листе «{ws.title}» не поддерживаются.")
    for merge in merges:
        ws.unmerge_cells(str(merge))
    old_max = ws.max_row
    last_column = ws.max_column
    helper_columns = [(cell.column, _key(cell.value)) for cell in ws[header] if _key(cell.value) in {"пр", "дост", "монт"}]
    source_headers = {}
    ws.delete_rows(first, old_max - first + 1)
    for r in list(ws.row_dimensions):
        if r >= first:
            del ws.row_dimensions[r]

    def moved_formula(value):
        if not isinstance(value, str) or not value.startswith('='):
            return value
        def ref(match):
            row = int(match[2])
            if row >= old_total:
                row += delta
            elif row >= first:
                row = new_total - 1 if row == old_total - 1 else min(row, new_total - 1)
            return match[1] + str(row)
        return re.sub(r'(\$?[A-Z]+\$?)(\d+)', ref, value)

    def restore(src, dst):
        if src in dimensions:
            ws.row_dimensions[dst] = copy(dimensions[src])
            ws.row_dimensions[dst].index = dst
        for original in cells[src]:
            target = ws.cell(dst, original.column)
            target._style = copy(original._style)
            target.value = moved_formula(original.value) if src >= old_total else _formula(original.value, original.coordinate, target.coordinate)
            target.comment = copy(original.comment)
            if original.hyperlink:
                target.hyperlink = copy(original.hyperlink)
                target.hyperlink.ref = target.coordinate

    for r in range(old_total, old_max + 1):
        restore(r, r + delta)
    for i in range(count):
        r = first + i
        restore(first, r)
        # Старые значения образца не попадают в новый объект; дополнительные формулы сохраняются.
        for col in range(1, last_column + 1):
            cell = ws.cell(r, col)
            if cell.data_type != "f":
                cell.value = None
                cell.hyperlink = None
                cell.comment = None
        if i >= len(sources):
            for col in range(1, last_column + 1):
                ws.cell(r, col).value = None
            continue
        source, source_row = sources[i]
        if id(source) not in source_headers:
            source_headers[id(source)] = {_key(c.value): c.column for c in source[3] if c.value is not None}
        source_columns = source_headers[id(source)]
        # Формулы стандартной формы переводятся по семантическим столбцам, а не по их порядку.
        mapping = {get_column_letter(col): get_column_letter(columns[label])
                   for label in columns if (col := source_columns.get(_key(label))) is not None}
        is_mounted = source.title == "1"
        qty = source.cell(source_row, 6).value
        vat = source.cell(source_row, 12 if is_mounted else 10).value
        price = source.cell(source_row, 13 if is_mounted else 11).value
        installation = (source.cell(source_row, 11).value or 0) if is_mounted else 0
        sale = price - installation if price is not None else None
        computed = {
            "Цена за ед. без НДС": sale / (1 + vat) if sale is not None else None,
            "Стоимость товара без НДС": sale / (1 + vat) * qty if sale is not None and qty is not None else None,
            "Цена за ед. товара, с НДС": sale,
            "Стоимость товара, с НДС": sale * qty if sale is not None and qty is not None else None,
            "Стоимость ед. товара (вкл. СМР), с НДС": price * qty if price is not None and qty is not None else None,
        }
        for label, col in columns.items():
            source_col = source_columns.get(_key(label))
            if source_col is None:
                continue
            value = source.cell(source_row, source_col).value
            if isinstance(value, str) and value.startswith("="):
                if all(ref in mapping for ref in re.findall(r"\b([A-Z]+)\d+\b", value)):
                    value = re.sub(r"\b([A-Z]+)(\d+)\b", lambda m: f"{mapping[m[1]]}{r}", value)
                else:
                    value = computed.get(label)
            ws.cell(r, col).value = i + 1 if renumber and label == "№" else value
        # Служебные проценты в исходной форме тоже относятся к новому объекту.
        for column, role in helper_columns:
            rates = {"пр": effective_markup(data.kp), "дост": data.kp.delivery_percent,
                     "монт": data.kp.installation_percent if is_mounted else 0}
            if role in rates:
                ws.cell(r, column).value = rates[role]
        # Высота строки растёт для длинного текста, но не становится меньше образца.
        original_height = (dimensions[first].height or 15) if first in dimensions else 15
        ws.row_dimensions[r].height = max(original_height, source.row_dimensions[source_row].height or 15)
    for merge in merges:
        shift = delta if merge.min_row >= old_total else 0
        ws.merge_cells(start_row=merge.min_row + shift, end_row=merge.max_row + shift,
                       start_column=merge.min_col, end_column=merge.max_col)
    # Сохраняем итоговые графы формы, обновляя диапазоны суммы.
    for col in columns.values():
        cell = ws.cell(new_total, col)
        if cell.data_type == "f" and re.match(r'^=SUM\(', cell.value, re.I):
            letter = get_column_letter(col)
            cell.value = f"=SUM({letter}{first}:{letter}{new_total - 1})"
    for row in ws.iter_rows(max_row=header):
        for cell in row:
            if cell.data_type == "f":
                cell.value = moved_formula(cell.value)
    def shift_area(value):
        return re.sub(r"(\$?[A-Z]+\$?)(\d+)", lambda m: m[1] + str(int(m[2]) + (delta if int(m[2]) >= old_total else 0)), value)
    if ws.print_area:
        ws.print_area = shift_area(str(ws.print_area))
    if ws.auto_filter.ref:
        ws.auto_filter.ref = f"A{header}:{get_column_letter(max(columns.values()))}{new_total - 1}"
    replacements = {"{{contract_number}}": data.kp.contract_number, "{{contract_date}}": format_date(data.kp.contract_date),
                    "{{title}}": data.title, "{{supplier_position}}": data.kp.supplier_position,
                    "{{customer_position}}": data.kp.customer_position}
    for row in ws:
        for cell in row:
            if isinstance(cell.value, str) and cell.data_type != "f":
                value = cell.value
                for marker, replacement in replacements.items():
                    value = value.replace(marker, replacement)
                if cell.row < header and re.search(r'Приложение.*к\s+Договор', value, re.I):
                    if data.kp.contract_number or data.kp.contract_date:
                        value = re.sub(r'(к\s+Договор[уа])\b.*',
                            lambda m: f'{m[1]} № {data.kp.contract_number or "___________"} от {format_date(data.kp.contract_date)}', value, flags=re.I)
                cell.value = value
