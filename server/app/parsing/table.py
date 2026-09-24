"""Разбор таблицы спецификации на странице: шапка, столбцы, строки, ячейки.

Алгоритм не привязан к конкретному проектировщику: столбцы узнаются по словам
шапки («Поз.», «Наименование», «Кол-во»…), границы берутся из линий таблицы,
а если линий нет (плохой скан) — из положения слов шапки и якорных ячеек.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .geometry import PageData, Word, group_into_lines

# Ключ столбца -> с чего начинается слово шапки (в нижнем регистре, без пробелов).
HEADER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "pos": ("поз",),
    "name": ("наименование",),
    "type_mark": ("тип",),
    "doc": ("обозначение",),
    "code": ("код",),
    "manufacturer": ("завод",),
    "unit": ("ед.", "ед", "единица"),
    "qty": ("кол-во", "кол.", "коли", "количество"),
    "mass": ("масса",),
    "note": ("примечание",),
}
# Без этих столбцов таблицу не считаем спецификацией.
REQUIRED_KEYS = {"pos", "name", "qty"}

# Слова основной надписи (штампа) внизу листа: по ним определяется, где кончается таблица.
STAMP_WORDS = {"изм.", "изм", "кол.уч.", "кол.уч", "лист", "подп.", "подп", "дата", "стадия", "листов"}

# Доля ширины/высоты таблицы, которую должна покрывать линия, чтобы считаться границей.
RULE_MIN_FRACTION = 0.35


@dataclass
class Column:
    key: str
    x0: float
    x1: float


@dataclass
class Row:
    y0: float
    y1: float
    cells: dict[str, str] = field(default_factory=dict)
    words: list[Word] = field(default_factory=list)


@dataclass
class TableLayout:
    columns: list[Column]
    header_top: float
    header_bottom: float
    table_bottom: float
    row_mode: str  # rules | anchors
    warnings: list[str] = field(default_factory=list)

    @property
    def x0(self) -> float:
        return self.columns[0].x0

    @property
    def x1(self) -> float:
        return self.columns[-1].x1

    def column_at(self, x: float) -> Column | None:
        for col in self.columns:
            if col.x0 <= x < col.x1:
                return col
        return None


def normalize_header_word(text: str) -> str:
    return re.sub(r"[\s,;:]+", "", text.lower())


def detect_layout(page: PageData) -> TableLayout | None:
    header = _find_header_words(page.words)
    if header is None:
        return None
    key_words, header_words = header
    header_top = min(w.y0 for w in header_words) - 2
    header_bottom = _header_bottom(page, header_words)
    table_bottom = _table_bottom(page, header_bottom, header_words)
    warnings: list[str] = []

    boundaries = _column_boundaries_from_rules(page, header_words, header_top, table_bottom)
    if boundaries is None:
        boundaries = _column_boundaries_from_header(header_words)
        warnings.append("границы столбцов определены по шапке (линии таблицы не найдены)")

    columns = _assign_columns(boundaries, key_words)
    if not REQUIRED_KEYS.issubset({c.key for c in columns}):
        return None

    row_mode = "rules" if _row_rules(page, columns, header_bottom, table_bottom) else "anchors"
    if row_mode == "anchors":
        warnings.append("строки разделены по якорным ячейкам (горизонтальные линии не найдены)")
    return TableLayout(columns, header_top, header_bottom, table_bottom, row_mode, warnings)


def extract_rows(page: PageData, layout: TableLayout) -> list[Row]:
    body_words = [
        w
        for w in page.words
        if layout.header_bottom <= w.cy < layout.table_bottom and layout.x0 <= w.cx < layout.x1
    ]
    if layout.row_mode == "rules":
        ys = _row_rules(page, layout.columns, layout.header_bottom, layout.table_bottom)
        ys = [layout.header_bottom] + [y for y in ys if y > layout.header_bottom + 3]
        if not ys or ys[-1] < layout.table_bottom - 3:
            ys.append(layout.table_bottom)
        bands = list(zip(ys, ys[1:]))
    else:
        bands = _anchor_bands(body_words, layout)

    rows: list[Row] = []
    for y0, y1 in bands:
        words = [w for w in body_words if y0 <= w.cy < y1]
        if not words:
            continue
        row = Row(y0, y1, words=words)
        for col in layout.columns:
            cell_words = [w for w in words if col.x0 <= w.cx < col.x1]
            if cell_words:
                row.cells[col.key] = _cell_text(cell_words)
        if _is_numbering_row(row):
            continue
        rows.append(row)
    return rows


def _is_numbering_row(row: Row) -> bool:
    """Строка «1 2 3 4 5 6 7 8 9» под шапкой — нумерация граф, а не данные."""
    values = list(row.cells.values())
    return len(values) >= 4 and all(re.fullmatch(r"\d{1,2}", v) for v in values)


# ---------- шапка ----------


def _find_header_words(words: list[Word]) -> tuple[dict[str, Word], list[Word]] | None:
    """Ищет полосу по вертикали, в которой встречается больше всего слов шапки."""
    candidates: list[tuple[str, Word]] = []
    for w in words:
        norm = normalize_header_word(w.text)
        for key, prefixes in HEADER_KEYWORDS.items():
            if any(norm.startswith(p) for p in prefixes):
                candidates.append((key, w))
                break
    if not candidates:
        return None

    best: dict[str, Word] = {}
    best_center = 0.0
    for _, anchor in candidates:
        band = {}
        for key, w in candidates:
            if abs(w.cy - anchor.cy) <= 30 and key not in band:
                band[key] = w
        if len(band) > len(best):
            best, best_center = band, anchor.cy
    if not REQUIRED_KEYS.issubset(best):
        return None

    # Полоса шапки: от верхнего до нижнего ключевого слова плюс полторы строки
    # текста с каждой стороны (в шапке бывают переносы: «Ед. / изме- / ре- / ния»).
    heights = sorted(w.height for w in best.values())
    line = heights[len(heights) // 2] * 1.5
    y0 = min(w.y0 for w in best.values()) - line
    y1 = max(w.y1 for w in best.values()) + line
    x0 = min(w.x0 for w in best.values()) - 5
    x1 = max(w.x1 for w in best.values()) + 5
    header_words = [w for w in words if y0 <= w.cy <= y1 and x0 <= w.cx <= x1]
    return best, header_words


def _header_bottom(page: PageData, header_words: list[Word]) -> float:
    text_bottom = max(w.y1 for w in header_words)
    width = max(w.x1 for w in header_words) - min(w.x0 for w in header_words)
    for y in page.rules.rows(width * RULE_MIN_FRACTION):
        if text_bottom - 1 <= y <= text_bottom + 25:
            return y
    return text_bottom + 3


def _table_bottom(page: PageData, header_bottom: float, header_words: list[Word]) -> float:
    """Верх основной надписи (штампа) или низ страницы.

    Слова штампа ищутся только под таблицей: на полях слева стоят такие же
    «Подп. и дата», «Инв. №», и их учитывать нельзя.
    """
    hx0 = min(w.x0 for w in header_words)
    hx1 = max(w.x1 for w in header_words)
    stamp_ys = [
        w.y0
        for w in page.words
        if w.text.lower() in STAMP_WORDS
        and hx0 <= w.cx <= hx1
        and w.cy > header_bottom + 40
        and w.cy > page.height * 0.5
    ]
    if stamp_ys:
        return min(stamp_ys) - 2
    return page.height - 5


# ---------- столбцы ----------


def _column_boundaries_from_rules(
    page: PageData, header_words: list[Word], top: float, bottom: float
) -> list[float] | None:
    """Вертикальные линии, покрывающие заметную часть высоты таблицы.

    Крайние границы берутся как ближайшие линии снаружи от текста шапки: сам
    текст стоит с отступом от рамки, и линия может быть на 15–20 пт левее слова.
    """
    hx0 = min(w.x0 for w in header_words)
    hx1 = max(w.x1 for w in header_words)
    xs = page.rules.columns((bottom - top) * RULE_MIN_FRACTION)
    left = [x for x in xs if x <= hx0 + 2]
    right = [x for x in xs if x >= hx1 - 2]
    inner = [x for x in xs if hx0 + 2 < x < hx1 - 2]
    if len(inner) < 3:
        return None
    return [left[-1] if left else hx0 - 4] + inner + [right[0] if right else hx1 + 4]


def _column_boundaries_from_header(header_words: list[Word]) -> list[float]:
    """Границы — середины промежутков между ячейками шапки (кластеры слов по x)."""
    cells: list[list[Word]] = []
    for w in sorted(header_words, key=lambda w: w.x0):
        if cells and w.x0 - max(c.x1 for c in cells[-1]) < 12:
            cells[-1].append(w)
        else:
            cells.append([w])
    edges = [(min(c.x0 for c in cell), max(c.x1 for c in cell)) for cell in cells]
    boundaries = [edges[0][0] - 4]
    for (_, right), (left, _) in zip(edges, edges[1:]):
        boundaries.append((right + left) / 2)
    boundaries.append(edges[-1][1] + 4)
    return boundaries


def _assign_columns(boundaries: list[float], key_words: dict[str, Word]) -> list[Column]:
    columns: list[Column] = []
    for x0, x1 in zip(boundaries, boundaries[1:]):
        keys = [k for k, w in key_words.items() if x0 <= w.cx < x1]
        key = keys[0] if keys else f"col_{len(columns)}"
        columns.append(Column(key, x0, x1))
    return columns


# ---------- строки ----------


def _row_rules(page: PageData, columns: list[Column], top: float, bottom: float) -> list[float]:
    width = columns[-1].x1 - columns[0].x0
    return [y for y in page.rules.rows(width * RULE_MIN_FRACTION) if top + 3 < y <= bottom + 3]


def _anchor_bands(words: list[Word], layout: TableLayout) -> list[tuple[float, float]]:
    """Строки по якорям: ячейки позиции/ед./кол-ва стоят по центру строки."""
    anchor_keys = {"pos", "unit", "qty"}
    anchors = sorted(
        {round(w.cy) for w in words if (c := layout.column_at(w.cx)) and c.key in anchor_keys}
    )
    merged: list[float] = []
    for y in anchors:
        if merged and y - merged[-1] < 8:
            merged[-1] = (merged[-1] + y) / 2
        else:
            merged.append(y)
    if not merged:
        return [(layout.header_bottom, layout.table_bottom)]
    bounds = [layout.header_bottom]
    bounds += [(a + b) / 2 for a, b in zip(merged, merged[1:])]
    bounds.append(layout.table_bottom)
    return list(zip(bounds, bounds[1:]))


def _cell_text(words: list[Word]) -> str:
    lines = [" ".join(w.text for w in line) for line in group_into_lines(words)]
    text = ""
    for line in lines:
        if not text:
            text = line
        elif text.endswith("-") and line[:1].islower():
            text = text[:-1] + line  # перенос слова по слогам
        else:
            text += " " + line
    return re.sub(r"\s+", " ", text).strip()
