"""Разбор спецификации из Excel (xlsx): шапка по словам заголовков, строки — в позиции.

Как и у PDF, столбцы узнаются по словам шапки («Поз.», «Наименование», «Кол-во»…), а не по
их месту: порядок столбцов любой. Нужны минимум «Наименование» и «Количество» (и «Поз.»,
если она есть). Объединённые ячейки разворачиваются (значение из левого верхнего угла
размножается на всю область), строки-заголовки без количества считаются разделом или
помещением — ровно как в PDF.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from openpyxl import load_workbook

from ..models import PageInfo, ParsedDocument, SpecItem
from .aggregate import build_summary
from .spec_parser import (
    DOC_CODE_RE,
    NO_POS_RE,
    POS_RE,
    TITLE_RE,
    _default_section,
    normalize_pos,
    parse_qty,
    short_name,
)

# Ключ столбца -> слова-приметы в заголовке (подстрока, в нижнем регистре). Порядок проверки
# важен: «Наименование помещения» — это раздел, а не наименование, поэтому раздел ищем раньше.
COLUMN_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("pos", ("поз", "№")),
    ("qty", ("кол-во", "колво", "кол.", "колич", "кол ")),
    ("unit", ("ед.", "ед ", "единиц", "ед-ц")),
    ("mass", ("масса", "вес")),
    ("code", ("код",)),
    ("manufacturer", ("завод", "изготов", "производ", "поставщик")),
    ("note", ("примеч", "коммент")),
    ("type_mark", ("тип", "марка", "артикул", "модель")),
    ("doc", ("обознач",)),
    ("group", ("раздел", "помещ")),
    ("name", ("наимен", "название", "оборудован", "характеристик")),
]
REQUIRED = ("name", "qty")  # без них лист не считаем спецификацией
HEADER_SCAN_ROWS = 60
MAX_HEADER_COLS = 60  # шире — вряд ли спецификация, не перебираем лишнее


def _text(value: object) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _expand_merges(ws) -> list[list[object]]:
    """Значения листа с развёрнутыми объединениями: значение левого верхнего угла — во все
    ячейки области (вертикальные объединения количества, горизонтальные заголовки разделов)."""
    grid: list[list[object]] = [list(row) for row in ws.iter_rows(values_only=True)]
    for rng in ws.merged_cells.ranges:
        top = grid[rng.min_row - 1][rng.min_col - 1] if rng.min_row - 1 < len(grid) else None
        if top is None:
            continue
        for r in range(rng.min_row - 1, min(rng.max_row, len(grid))):
            for c in range(rng.min_col - 1, rng.max_col):
                if c < len(grid[r]):
                    grid[r][c] = top
    return grid


def _match_header(cells: list[str]) -> dict[str, int] | None:
    """Строка шапки -> {ключ столбца: индекс}. Каждый столбец — не больше одного ключа."""
    lower = [c.lower() for c in cells]
    mapping: dict[str, int] = {}
    used: set[int] = set()
    for key, hints in COLUMN_HINTS:
        for i, cell in enumerate(lower):
            if i in used or not cell:
                continue
            if any(h in cell for h in hints):
                mapping[key] = i
                used.add(i)
                break
    return mapping if all(k in mapping for k in REQUIRED) else None


def _find_header(grid: list[list[object]]) -> tuple[int, dict[str, int]] | None:
    """Строка шапки — первая из первых строк, где нашлись все обязательные столбцы, и при
    равенстве — с наибольшим числом узнанных столбцов (бывает двухэтажная шапка)."""
    best: tuple[int, dict[str, int]] | None = None
    for r, row in enumerate(grid[:HEADER_SCAN_ROWS]):
        cells = [_text(v) for v in row[:MAX_HEADER_COLS]]
        mapping = _match_header(cells)
        if mapping is not None and (best is None or len(mapping) > len(best[1])):
            best = (r, mapping)
    return best


def _cell(row: list[object], mapping: dict[str, int], key: str) -> str:
    i = mapping.get(key)
    return _text(row[i]) if i is not None and i < len(row) else ""


def parse_xlsx(source: str | Path | bytes, file_name: str | None = None) -> ParsedDocument:
    if isinstance(source, (bytes, bytearray)):
        name = file_name or "спецификация.xlsx"
        handle: object = io.BytesIO(bytes(source))
    else:
        name = file_name or Path(source).name
        handle = str(source)
    # data_only=True берёт посчитанные значения формул; объединения разворачиваем сами,
    # поэтому read_only не используем (в нём merged_cells.ranges недоступны).
    wb = load_workbook(handle, read_only=False, data_only=True)
    result = ParsedDocument(file_name=name)
    items: list[SpecItem] = []
    pre_header_text: list[str] = []

    for ws in wb.worksheets:
        grid = _expand_merges(ws)
        found = _find_header(grid)
        if found is None:
            continue
        header_row, mapping = found
        pre_header_text += [_text(v) for row in grid[:header_row] for v in row if _text(v)]
        sheet_items = _rows_to_items(grid[header_row + 1 :], mapping, len(items))
        items.extend(sheet_items)
        result.pages.append(PageInfo(number=len(result.pages) + 1, kind="spec", source="xlsx", rows=len(sheet_items)))

    wb.close()
    result.items = items
    result.summary = build_summary(items)
    _fill_metadata(result, pre_header_text, name)
    default_section = _default_section(result.spec_title)
    for summary in result.summary:
        summary.section = summary.section or default_section
        summary.source_doc = result.doc_code
    for item in items:
        item.source_doc = result.doc_code
    if not result.pages:
        result.warnings.append("в книге не найдено листа со столбцами «Наименование» и «Количество»")
    result.documents = [result.source_summary()]
    return result


def _rows_to_items(rows: list[list[object]], mapping: dict[str, int], next_id: int) -> list[SpecItem]:
    items: list[SpecItem] = []
    group = ""
    for row in rows:
        pos = _cell(row, mapping, "pos")
        name = _cell(row, mapping, "name")
        unit = _cell(row, mapping, "unit")
        qty_raw = _cell(row, mapping, "qty")
        section = _cell(row, mapping, "group")
        if not name and not pos and not section:
            continue
        # Строка без единицы и количества — заголовок раздела или помещения.
        if not unit and not qty_raw:
            header = section or f"{pos} {name}".strip()
            if header:
                group = header
            continue
        item = SpecItem(
            id=next_id + len(items) + 1,
            page=1,
            pos=pos,
            pos_key=normalize_pos(pos),
            description=name,
            name=short_name(name),
            type_mark=_cell(row, mapping, "type_mark") or _cell(row, mapping, "doc"),
            code=_cell(row, mapping, "code"),
            manufacturer=_cell(row, mapping, "manufacturer"),
            unit=unit,
            qty_raw=qty_raw,
            mass=_cell(row, mapping, "mass"),
            note=_cell(row, mapping, "note"),
            group=section or group,
        )
        item.qty = parse_qty(qty_raw)
        if item.qty is None:
            item.warnings.append(f"не удалось прочитать количество: «{qty_raw}»")
        if not pos:
            item.warnings.append("нет номера позиции")
        elif not (POS_RE.match(pos) or NO_POS_RE.match(pos)):
            item.warnings.append(f"необычный номер позиции: «{pos}»")
        if not name:
            item.warnings.append("пустое наименование")
        if not unit:
            item.warnings.append("нет единицы измерения")
        items.append(item)
    return items


def _fill_metadata(result: ParsedDocument, texts: list[str], file_name: str) -> None:
    joined = " ".join(texts)
    m = DOC_CODE_RE.search(joined)
    result.doc_code = m.group(0) if m else Path(file_name).stem
    m = TITLE_RE.search(joined)
    if m:
        result.title = re.sub(r"\s+", " ", m.group(1)).strip()
    spec = re.search(r"Спецификац[а-я]*[^.]*", joined, re.I)
    if spec:
        result.spec_title = re.sub(r"\s+", " ", spec.group(0)).strip()[:120]
