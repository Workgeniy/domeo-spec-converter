"""Чтение истории закупок — выгрузки из 1С «Заказы поставщикам» (xlsx).

Одна строка выгрузки = позиция спецификации проекта (Номенклатура, описание, группа) и
строка заказа поставщику (что реально купили, сколько и на какую сумму). Цена за единицу =
ЗаказаноСумма / ЗаказаноКоличество. Часть строк — компоненты сборок: у них цена относится
к компоненту, а не к позиции, поэтому такие строки собираются в один комплект.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import openpyxl

# Как называются графы в выгрузке 1С → как называем их мы. Ищем по началу имени, чтобы
# пережить мелкие отличия выгрузок.
COLUMNS = {
    "line": "Номер строки",
    "name": "Номенклатура",
    "description": "Текстовое описание",
    "spec_qty": "Количество",
    "group": "Группа аналитического учета",
    "assembly": "Заказы на сборку",
    "assemble_qty": "Количество собрать",
    "component": "Комплектующая номенклатура",
    "component_qty": "Количество комплектующих",
    "order": "ЗаказаноДокумент",
    "partner_item": "Номенклатура партнера",
    "qty": "ЗаказаноКоличество",
    "total": "ЗаказаноСумма",
}
ORDER_DATE_RE = re.compile(r"от (\d{2}\.\d{2}\.\d{4})")
STOPWORDS = {"для", "и", "в", "с", "не", "менее", "более", "из", "по", "на", "тип", "шт", "или", "к", "от", "до"}


@dataclass(frozen=True)
class PurchaseRow:
    """Строка истории после разбора: либо покупка позиции, либо компонент сборки."""

    name: str
    description: str
    group: str
    order: str
    order_date: date | None
    partner_item: str
    qty: float | None
    total: float | None
    assembly: str  # идентификатор заказа на сборку; пусто — обычная покупка
    assemble_qty: float | None
    component: str

    @property
    def unit_price(self) -> float | None:
        if self.qty and self.total is not None and self.qty > 0:
            return self.total / self.qty
        return None


def normalize_name(text: str) -> str:
    """Ключ сопоставления: строчные буквы, ё→е, без пунктуации и лишних пробелов."""
    text = str(text or "").lower().replace("ё", "е")
    text = re.sub(r"[^а-яa-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> set[str]:
    """Значимые слова наименования — для индекса нестрогого поиска."""
    return {t for t in normalize_name(text).split() if len(t) >= 3 and t not in STOPWORDS}


def read_history(path: str | Path) -> list[PurchaseRow]:
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [str(h or "").strip() for h in next(rows)]
    index = {key: _find_column(header, title) for key, title in COLUMNS.items()}
    missing = [COLUMNS[k] for k in ("name", "order", "qty", "total") if index[k] is None]
    if missing:
        raise ValueError(f"в выгрузке нет граф: {', '.join(missing)}")

    def cell(row: tuple, key: str) -> object:
        i = index[key]
        return row[i] if i is not None and i < len(row) else None

    result: list[PurchaseRow] = []
    for row in rows:
        name = str(cell(row, "name") or "").strip()
        if not name:
            continue
        order = str(cell(row, "order") or "").strip()
        result.append(
            PurchaseRow(
                name=name,
                description=_clean(cell(row, "description")),
                group=_clean(cell(row, "group")),
                order=order,
                order_date=_order_date(order),
                partner_item=_clean(cell(row, "partner_item")),
                qty=_number(cell(row, "qty")),
                total=_number(cell(row, "total")),
                assembly=_clean(cell(row, "assembly")),
                assemble_qty=_number(cell(row, "assemble_qty")),
                component=_clean(cell(row, "component")),
            )
        )
    return result


def _find_column(header: list[str], title: str) -> int | None:
    for i, h in enumerate(header):
        if h.lower().startswith(title.lower()):
            return i
    return None


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip() if value is not None else ""


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def _order_date(order: str) -> date | None:
    m = ORDER_DATE_RE.search(order)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d.%m.%Y").date()
    except ValueError:
        return None
