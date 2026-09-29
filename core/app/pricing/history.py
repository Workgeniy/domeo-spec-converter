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
from typing import NamedTuple

import openpyxl

from .synonyms import ADJECTIVE_END, RUSSIAN_WORD, canonical_stems, plain_stems, stem

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


def significant_words(text: str) -> list[str]:
    """Значимые слова наименования как есть: без коротких и служебных."""
    return [t for t in normalize_name(text).split() if len(t) >= 3 and t not in STOPWORDS]


def stems(text: str) -> list[str]:
    """Значимые слова наименования по порядку — основами и через словарь (synonyms.py):
    «перфорированный» и «перфорированными», «ванна моечная» и «мойка» дают одно и то же."""
    return canonical_stems(significant_words(text))


def tokens(text: str) -> set[str]:
    """Те же основы набором — для индекса нестрогого поиска."""
    return set(stems(text))


def loose_tokens(text: str) -> set[str]:
    """Основы и до, и после замены оборотов — для проверки «есть ли вообще общие слова»."""
    return analyze_name(text).loose


class NameWords(NamedTuple):
    """Разбор наименования для сопоставления — всё за один проход."""

    key: str  # normalize_name
    stems: list[str]  # значимые слова основами, по порядку (см. stems)
    loose: set[str]  # основы и до, и после замены оборотов
    head: str  # главное слово — основа
    head_word: str  # главное слово как написано — чтобы видеть число


def analyze_name(text: str) -> NameWords:
    """Главное слово — первое, которое не прилагательное: у «Шкаф холодильный» и «Холодильный
    шкаф» это шкаф, у «Обеденный стол с 4 стульями» — стол. Если первым идёт не русское слово
    (марка, модель), главное слово не определяем. Как написано — чтобы видеть число: «Стулья
    с пюпитром» у магазина — раздел каталога, «Стул с пюпитром» в проекте — товар."""
    key = normalize_name(text)
    words = [t for t in key.split() if len(t) >= 3 and t not in STOPWORDS]
    canonical = canonical_stems(words)
    adjectives = {stem(w) for w in words if ADJECTIVE_END.search(w)}
    head = next((s for s in canonical if s not in adjectives), "")
    first_noun = next((w for w in words if not ADJECTIVE_END.search(w)), "")
    return NameWords(
        key=key,
        stems=canonical,
        loose=set(canonical) | plain_stems(words),
        head=head if RUSSIAN_WORD.fullmatch(head) else "",
        head_word=first_noun if RUSSIAN_WORD.fullmatch(first_noun) else "",
    )


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
    try:
        for row in rows:
            parsed = _parse_row(row, cell)
            if parsed is not None:
                result.append(parsed)
    finally:
        wb.close()  # read-only книга держит файл открытым, пока её не закроют
    return result


def _parse_row(row: tuple, cell) -> PurchaseRow | None:
    name = str(cell(row, "name") or "").strip()
    if not name:
        return None
    order = str(cell(row, "order") or "").strip()
    return PurchaseRow(
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
