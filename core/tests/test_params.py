from __future__ import annotations

from app.pricing.params import Params, compare_params, extract_params


def test_dimensions_in_all_common_forms() -> None:
    assert extract_params("Стол, ЛДСП 16мм, 1100х500х460/520/580(h)").dims == [[(1100, 500, 460), (1100, 500, 520), (1100, 500, 580)]]
    assert extract_params("Игровой модуль, 550х405х885(h)").dims == [[(550, 405, 885)]]
    assert extract_params("Стеллаж 2000x1000x400 мм с 4 полками").dims == [[(2000, 1000, 400)]]
    assert extract_params("Стеллаж 2,0×1,0×0,4 м").dims == [[(2000, 1000, 400)]]
    assert extract_params("Доска 120х60 см").dims == [[(1200, 600)]]
    assert extract_params("Стул регулируемый №1-№3, группа роста 1-3, комплект 2х4 шт").dims == []  # мелкие числа — не габариты
    assert extract_params("").empty()


def test_scalar_params() -> None:
    p = extract_params("Шкаф холодильный 700 л, 0…+6 °C, 1,2 кВт, 220 В, масса 120 кг, Ø 400 мм")
    assert p.volume_l == [700] and p.mass_kg == [120] and p.power_kw == [1.2] and p.diameter_mm == [400]
    assert extract_params("мощность 750 Вт").power_kw == [0.75]
    assert p.describe() == "700 л 120 кг 1,2 кВт Ø400"
    assert extract_params("Стеллаж 2000x1000x400, 4 полки").describe() == "2000x1000x400"


def test_compare_matches_conflicts_and_unknown() -> None:
    spec = extract_params("Стеллаж с перфорированными полками, 2000х1000х400(h)")
    assert compare_params(spec, extract_params("Стеллаж 2000x1000x400 с 4 перфорированными полками")) == (1, 0, 0)
    assert compare_params(spec, extract_params("Стеллаж 400x1000x2000")) == (1, 0, 0)  # другой порядок осей
    assert compare_params(spec, extract_params("Стеллаж 2010x1000x400")) == (1, 0, 0)  # в допуске
    assert compare_params(spec, extract_params("Стеллаж 2500x1000x400 с 4 полками")) == (0, 1, 0)
    assert compare_params(spec, extract_params("Стеллаж 2000x1000")) == (1, 0, 0)  # две оси из трёх
    assert compare_params(spec, extract_params("Стеллаж перфорированный")) == (0, 0, 1)  # размер не указан
    assert compare_params(Params(), extract_params("Стеллаж 2500x1000x400")) == (0, 0, 0)  # у позиции нет параметров
    fridge = extract_params("Шкаф холодильный среднетемпературный 700л")
    assert compare_params(fridge, extract_params("Шкаф холодильный Polair CM107-S, 700 л")) == (1, 0, 0)
    assert compare_params(fridge, extract_params("Шкаф холодильный Polair CM105-S, 500 л")) == (0, 1, 0)


def test_counts_sections_burners_shelves() -> None:
    assert extract_params("Ванна котломоечная двухсекционная").counts == {"секций": {2}}
    assert extract_params("Плита электрическая 4-х конфорочная").counts == {"конфорок": {4}}
    assert extract_params("Шкаф двухстворчатый, с двумя дверями").counts == {"створок": {2}, "дверей": {2}}
    assert extract_params("Стеллаж 5-ти ярусный, 4 полки").counts == {"ярусов": {5}, "полок": {4}}
    assert extract_params("Кровать двухъярусная; модуль для сна на 25 мест").counts == {"ярусов": {2}, "мест": {25}}
    assert extract_params("Полотенце махровое").counts == {}
    two = extract_params("Ванна котломоечная двухсекционная")
    assert compare_params(two, extract_params("Ванна котломоечная односекционная ВК 1-э")) == (0, 1, 0)
    assert compare_params(two, extract_params("Ванна котломоечная 2-х секционная")) == (1, 0, 0)
    assert compare_params(two, extract_params("Ванна котломоечная ВК-2")) == (0, 0, 1)  # число секций не указано
    # Счётные признаки — в комментарий оператору, но не в запрос поисковику (в названии они уже есть).
    shelves = extract_params("Стеллаж 2000x1000x400, 4 полки")
    assert shelves.describe() == "2000x1000x400" and shelves.describe(counts=True) == "2000x1000x400 полок 4"
