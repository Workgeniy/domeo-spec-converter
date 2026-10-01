from __future__ import annotations

from app.models import SearchParam
from app.pricing.attributes import CONFLICT, MATCH, UNKNOWN, check, clean_params, described_params, params_key, parse_params
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


def labels(name: str, description: str) -> list[str]:
    return [w.label for w in described_params(name, description)]


def test_params_from_description() -> None:
    assert labels("Стол производственный", "Стол производственный, нержавеющая сталь, борт, полка, 1000х600х870(h)") == [
        "материал — нержавеющая сталь",
        "с бортом",
        "с полкой",
    ]
    # Материал части — по перечислению через запятую: «цвет каркаса хромированный» — о каркасе.
    chair = "Стул офисный на металлическом каркасе, каркас металлическая труба, цвет каркаса хромированный, сиденье и спинка - экокожа"
    assert labels("Стул офисный", chair) == ["материал каркаса — хром", "материал сиденья — экокожа", "материал спинки — экокожа"]
    assert labels("Стол обеденный", "Стол обеденный, столешница ЛДСП, ножки металл") == ["материал столешницы — ЛДСП", "материал ножек — металл"]
    # Порода дерева при ЛДСП — цвет декора; «МДФ/ЛДСП» — любой из двух.
    assert labels("Стол воспитателя", "Стол воспитателя, МДФ/ЛДСП толщиной 16мм, цвет бук") == ["материал — МДФ или ЛДСП"]
    # «пристенный или островной» — выбор, а не признак.
    assert labels("Стол", "Стол пристенный или островной, нержавеющая сталь") == ["материал — нержавеющая сталь"]


def test_params_from_description_checks() -> None:
    table = described_params("Стол производственный", "Стол производственный, нержавеющая сталь, борт, полка")

    def verdicts(title: str) -> list[str]:
        return [check(w, normalize_name(title), analyze_name(title).loose) for w in table]

    assert verdicts("Стол СРТ-ПН AISI 304 с бортом и полкой") == [MATCH, MATCH, MATCH]
    assert verdicts("Стол производственный оцинкованный с полкой") == [CONFLICT, UNKNOWN, MATCH]
    assert verdicts("Стол производственный без борта") == [UNKNOWN, CONFLICT, UNKNOWN]
    # Материалы разных семейств (пластиковый бак, нержавеющая тележка) — без противоречия.
    cart = described_params("Тележка с баком", "Тележка с баком, бак - пластик, тележка - нержавеющая сталь")
    assert [w.soft for w in cart] == [True]
    assert check(cart[0], normalize_name("Тележка оцинкованная"), analyze_name("Тележка оцинкованная").loose) == UNKNOWN
    # Материал при части в названии предложения («пластиковый корпус») — не о всём изделии.
    scales = described_params("Весы напольные", "Весы напольные, платформа нержавеющая сталь")
    assert check(scales[0], normalize_name("Весы напольные, пластиковый корпус"), analyze_name("Весы напольные пластиковый корпус").loose) == UNKNOWN
    assert check(scales[0], normalize_name("Весы напольные из пластика"), analyze_name("Весы напольные из пластика").loose) == CONFLICT
    # Что оператор задал сам, из характеристик не берётся.
    manual = parse_params([SearchParam(name="Материал", value="металл")])
    assert [w.label for w in described_params("Стол производственный", "нержавеющая сталь, борт", manual)] == ["с бортом"]


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
