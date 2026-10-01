from __future__ import annotations

from app.models import SearchParam
from app.pricing.attributes import CONFLICT, MATCH, UNKNOWN, check, clean_params, params_key, parse_params
from app.pricing.history import analyze_name, normalize_name


def statuses(params: list[tuple[str, str]], title: str) -> list[str]:
    manual = parse_params([SearchParam(name=n, value=v) for n, v in params])
    return [check(w, normalize_name(title), analyze_name(title).loose) for w in manual.wanted]


def test_material_with_family() -> None:
    metal = [("Материал", "металл")]
    assert statuses(metal, "Стол из нержавеющей стали") == [MATCH]  # частный случай металла
    assert statuses(metal, "Стол обеденный деревянный") == [CONFLICT]
    assert statuses(metal, "Стол обеденный Masey") == [UNKNOWN]
    stainless = [("Материал", "нержавеющая сталь")]
    assert statuses(stainless, "Стол нерж. AISI 304") == [MATCH]
    assert statuses(stainless, "Стол производственный из стали") == [UNKNOWN]  # сталь — общее, не опровергает
    assert statuses(stainless, "Стол оцинкованная сталь") == [CONFLICT]
    assert statuses([("Материал", "дерево")], "Стол из массива березы") == [MATCH]
    # Порода дерева рядом с ЛДСП — цвет декора, а не материал.
    assert statuses([("Материал", "дерево")], "Шкаф ЛДСП дуб сонома") == [CONFLICT]
    assert statuses([("Материал", "ДСП")], "Шкаф ЛДСП") == [MATCH] and statuses([("Материал", "ЛДСП")], "Шкаф ДСП") == [UNKNOWN]
    assert statuses([("Материал", "дерево")], "Конструктор Деревенский дом") == [UNKNOWN]  # «деревенский» — не дерево


def test_material_of_a_part() -> None:
    legs = [("Материал ножек", "металл")]
    assert statuses(legs, "Стол обеденный, столешница ЛДСП, ножки металл") == [MATCH]
    assert statuses(legs, "Стул на металлических ножках") == [MATCH]
    assert statuses(legs, "Стол на металлокаркасе") == [MATCH]  # ножки не названы — смотрим материал по всему названию
    assert statuses(legs, "Стол с ножками из массива бука") == [CONFLICT]
    # Ножки не названы — ЛДСП может быть о столешнице: не противоречие, а «не указано».
    assert statuses(legs, "Стол обеденный, ЛДСП") == [UNKNOWN]
    assert statuses([("Материал столешницы", "МДФ")], "Стол, столешница ЛДСП, ножки металл") == [CONFLICT]
    assert statuses([("Материал столешницы", "металл")], "Стол, столешница ЛДСП, ножки металл") == [CONFLICT]  # металл — у ножек
    assert statuses([("Обивка", "экокожа")], "Диван, обивка кожа") == [CONFLICT]
    assert statuses([("Обивка", "экокожа")], "Диван, обивка экокожа") == [MATCH]


def test_colour_and_free_text() -> None:
    grey = [("Цвет", "серый")]
    assert statuses(grey, "Стул серый") == [MATCH] and statuses(grey, "Стул бело-серый") == [MATCH]
    assert statuses(grey, "Стул серии ИЗО, черный") == [CONFLICT]  # «серии» — не цвет
    assert statuses(grey, "Стул ИЗО") == [UNKNOWN]
    assert statuses([("Цвет каркаса", "черный")], "Стол ЛДСП, каркас белый, столешница черная") == [CONFLICT]
    assert statuses([("Производитель", "Abat")], "Пароконвектомат Abat ПКА 6-1/1ПП2") == [MATCH]
    assert statuses([("Производитель", "Abat")], "Пароконвектомат Rational iCombi") == [UNKNOWN]  # без словаря — не опровергаем


def test_parse_clean_and_query() -> None:
    manual = parse_params(
        [
            SearchParam(name=" Материал  ножек ", value="металл"),
            SearchParam(name="Объём", value="20 л"),
            SearchParam(name="Цвет", value=""),  # пустое значение — не параметр
            SearchParam(name="материал ножек", value="Металл"),  # повтор
        ]
    )
    assert [(p.name, p.value) for p in manual.items] == [("Материал ножек", "металл"), ("Объём", "20 л")]
    assert manual.describe() == "материал ножек — металл; объём — 20 л"
    assert manual.query() == "ножки металл" and manual.numeric_text == "20 л" and manual.required.volume_l == [20]
    assert manual.checkable() and not parse_params([]).checkable()
    assert len(clean_params([SearchParam(name=f"п{i}", value="x") for i in range(30)])) == 10
    # Ключ кэша не зависит от порядка и регистра.
    assert params_key([SearchParam(name="Цвет", value="Серый"), SearchParam(name="Материал", value="металл")]) == params_key(
        [SearchParam(name="материал", value="Металл"), SearchParam(name="цвет", value="серый")]
    )
