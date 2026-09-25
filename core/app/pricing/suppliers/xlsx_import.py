"""Прайс-лист поставщика из xlsx: находим строку шапки с «наименованием» и «ценой», дальше —
строки с названием и числом. Формы у всех разные, поэтому только эвристика."""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from .extract import Extracted, parse_price

NAME_HINTS = ("наимен", "название", "номенклатур", "товар", "продукц", "позиц", "описание")
PRICE_HINTS = ("цена", "стоимость", "price", "руб")
PRICE_PREFER = ("с ндс", "розн", "цена")
SKU_HINTS = ("артикул", "код", "sku")
HEADER_SCAN_ROWS = 40


def _cell(value: object) -> str:
    return " ".join(str(value).split()).strip() if value is not None else ""


def _find_header(rows: list[tuple[object, ...]]) -> tuple[int, int, int, int | None] | None:
    """(строка шапки, колонка названия, колонка цены, колонка артикула)."""
    for r, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        cells = [_cell(v).lower() for v in row]
        name_col = next((i for i, c in enumerate(cells) if any(h in c for h in NAME_HINTS)), None)
        price_cols = [i for i, c in enumerate(cells) if any(h in c for h in PRICE_HINTS)]
        if name_col is None or not price_cols:
            continue
        price_col = next((i for hint in PRICE_PREFER for i in price_cols if hint in cells[i]), price_cols[0])
        sku_col = next((i for i, c in enumerate(cells) if any(h in c for h in SKU_HINTS) and i != name_col), None)
        return r, name_col, price_col, sku_col
    return None


def _guess_columns(rows: list[tuple[object, ...]]) -> tuple[int, int] | None:
    """Без шапки: колонка с самыми длинными текстами — название, первая числовая правее — цена."""
    width = max((len(r) for r in rows), default=0)
    text_len = [0] * width
    numeric = [0] * width
    for row in rows[:200]:
        for i, value in enumerate(row):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric[i] += 1
            elif isinstance(value, str) and len(value.strip()) > 8:
                text_len[i] += len(value)
    if not any(text_len):
        return None
    name_col = max(range(width), key=lambda i: text_len[i])
    price_col = next((i for i in range(width) if i != name_col and numeric[i] >= 3), None)
    return (name_col, price_col) if price_col is not None else None


def read_price_list(path: str | Path) -> list[Extracted]:
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        offers: list[Extracted] = []
        for ws in wb.worksheets:
            rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
            if not rows:
                continue
            header = _find_header(rows)
            if header is not None:
                start, name_col, price_col, sku_col = header
                start += 1
            else:
                guess = _guess_columns(rows)
                if guess is None:
                    continue
                name_col, price_col = guess
                start, sku_col = 0, None
            for row in rows[start:]:
                name = _cell(row[name_col]) if name_col < len(row) else ""
                price = parse_price(row[price_col]) if price_col < len(row) else None
                if not name or price is None or len(name) < 3:
                    continue
                sku = _cell(row[sku_col]) if sku_col is not None and sku_col < len(row) else ""
                offers.append(Extracted(name=name, price=price, sku=sku, source="xlsx"))
        return offers
    finally:
        wb.close()
