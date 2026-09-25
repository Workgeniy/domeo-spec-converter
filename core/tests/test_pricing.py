from __future__ import annotations

from datetime import date
from pathlib import Path

import openpyxl
import pytest

from app.pricing.history import normalize_name, read_history, tokens
from app.pricing.matching import Matcher
from app.pricing.pricelist import PriceList, build_from_file, build_price_list

from .conftest import sample

HEADER = [
    "Номер строки", "Номенклатура", "Текстовое описание", "Количество", "Группа аналитического учета",
    "Заказы на сборку", "Количество собрать", "Комплектующая номенклатура", "Количество комплектующих",
    "ЗаказаноДокумент", "Номенклатура партнера", "ЗаказаноКоличество", "ЗаказаноСумма",
]


@pytest.fixture
def history_xlsx(tmp_path: Path) -> Path:
    rows = [
        ["1", "Стул детский регулируемый", "Стул детский, фанера", "26", "Мебель", None, None, None, None, "Заказ поставщику БАУТ-000001 от 10.02.2023", "Стул «Малыш» гр.1-3", "26", "26000"],
        ["1", "Стул детский регулируемый", "Стул детский, фанера", "10", "Мебель", None, None, None, None, "Заказ поставщику БАУТ-000002 от 15.06.2024", "Стул «Малыш» гр.1-3", "10", "12000"],
        ["1", "Стул детский регулируемый ", None, "5", "Мебель", None, None, None, None, "Заказ поставщику БАУТ-000003 от 01.03.2025", "Стул детский", "5", "7000"],
        ["1", "стул детский регулируемый", None, "1", "Мебель", None, None, None, None, "Заказ поставщику БАУТ-000004 от 01.04.2025", "Стул детский", "1", "1"],  # артефакт: 1 ₽
        ["2", "Набор волчков", "Набор из 6 волчков", "3", "Игры и игрушки", "Заказ на сборку БАУТ-000010 от 20.09.2024", "3", "Волчок фигурный", "18", "Заказ поставщику БАУТ-000005 от 20.09.2024", "Волчок (RNToys)", "18", "1800"],
        ["2", "Набор волчков", "Набор из 6 волчков", "3", "Игры и игрушки", "Заказ на сборку БАУТ-000010 от 20.09.2024", "3", "Коробка", "3", "Заказ поставщику БАУТ-000005 от 20.09.2024", "Коробка картонная", "3", "300"],
        ["3", "Шкаф холодильный среднетемпературный", "Шкаф 700 л", "1", "Торгово-технологическое оборудование", None, None, None, None, "Заказ поставщику БАУТ-000006 от 05.05.2025", "Polair CM107-S", "1", "85000"],
        ["4", "Позиция без цены", None, "1", "Мебель", None, None, None, None, "Заказ поставщику БАУТ-000007 от 05.05.2025", None, None, None],
    ]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADER)
    for r in rows:
        ws.append(r)
    path = tmp_path / "история.xlsx"
    wb.save(path)
    return path


def test_normalize_and_tokens() -> None:
    assert normalize_name(" Стул  детский, регулируемый (гр. 1–3) ") == "стул детский регулируемый гр 1 3"
    assert normalize_name("Ёлка") == normalize_name("елка")
    assert tokens("Стол для воспитателя, ЛДСП") == {"стол", "воспитателя", "лдсп"}


def test_read_history_parses_rows(history_xlsx: Path) -> None:
    rows = read_history(history_xlsx)
    assert len(rows) == 8
    first = rows[0]
    assert first.name == "Стул детский регулируемый" and first.group == "Мебель"
    assert first.order_date == date(2023, 2, 10) and first.unit_price == 1000.0
    assert rows[4].assembly.startswith("Заказ на сборку") and rows[4].assemble_qty == 3
    assert rows[7].unit_price is None


def test_build_price_list_merges_names_sets_and_outliers(history_xlsx: Path) -> None:
    price_list = build_from_file(history_xlsx)
    by_key = price_list.by_key()
    # Три написания одного стула — одна позиция; покупка за 1 ₽ помечена выбросом и в эталоны не вошла.
    chair = by_key["стул детский регулируемый"]
    assert chair.count == 4 and sum(p.outlier for p in chair.purchases) == 1
    assert (chair.price_min, chair.price_max, chair.price_median) == (1000.0, 1400.0, 1200.0)
    assert chair.price_last == 1400.0 and chair.last_date == date(2025, 3, 1)  # выброс 01.04.2025 не считается последней ценой
    assert chair.descriptions == ["Стул детский, фанера"]
    # Сборка: два компонента на три комплекта → одна покупка по 700 за комплект.
    tops = by_key["набор волчков"]
    assert tops.count == 1 and tops.purchases[0].unit_price == 700.0 and tops.purchases[0].partner_item == "комплект: 2 компонентов"
    # Строка без цены не даёт позиции.
    assert "позиция без цены" not in by_key
    assert price_list.rows_total == 8 and len(price_list.entries) == 3


def test_price_list_roundtrip(history_xlsx: Path, tmp_path: Path) -> None:
    price_list = build_from_file(history_xlsx)
    path = tmp_path / "прайс.json"
    price_list.save(path)
    loaded = PriceList.load(path)
    assert [e.key for e in loaded.entries] == [e.key for e in price_list.entries]
    assert loaded.by_key()["стул детский регулируемый"].purchases[0].purchased_at == date(2025, 4, 1)


def test_matcher_levels(history_xlsx: Path) -> None:
    matcher = Matcher(build_from_file(history_xlsx))
    exact = matcher.match("Стул детский регулируемый")
    assert exact.kind == "exact" and exact.best is not None and exact.best.price_min == 1000.0
    fuzzy = matcher.match("Стул детский регулируемый по высоте №1-№3")
    assert fuzzy.kind == "fuzzy" and fuzzy.best is not None and fuzzy.best.key == "стул детский регулируемый"
    analog = matcher.match("Шкаф холодильный")
    assert analog.kind in ("fuzzy", "analog") and analog.best is not None and "холодильный" in analog.best.name.lower()
    nothing = matcher.match("Проектор мультимедийный")
    assert nothing.kind == "none" and nothing.best is None


# ---------- реальная выгрузка (пропускается, если образца нет) ----------


def test_real_history_builds_and_covers_specs() -> None:
    price_list = build_from_file(sample("База_для_ИИ_заполнено_обезличено.xlsx"))
    assert price_list.rows_total > 28000 and len(price_list.entries) > 8500
    matcher = Matcher(price_list)
    assert matcher.match("Стул офисный").kind == "exact"
    assert matcher.match("Кровать детская двухуровневая").kind in ("exact", "fuzzy")
