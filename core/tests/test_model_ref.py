from __future__ import annotations

from app.pricing.model_ref import code_tokens, reference_model


def test_reference_model_from_type_mark() -> None:
    assert reference_model("по типу Polair CM107-S").text == "Polair CM107-S"
    assert reference_model("по типу Polair CM107-S").code == "cm107s"
    assert reference_model("Бирюса 110 или аналог").text == "Бирюса 110"
    assert reference_model("ВМ-12/500 или аналог").code == "bm12500"  # русские В и М — как латинские
    assert reference_model("АСК-ШМО.01.00(мод.1) или аналог").text == "АСК-ШМО.01.00(мод.1)"
    # Не товар: пусто, прочерк, обозначение документа, марка без номера.
    assert reference_model("") is None and reference_model("—") is None
    assert reference_model("ГОСТ 23332-78") is None and reference_model("Атлант") is None


def matches(type_mark: str, title: str) -> bool:
    model = reference_model(type_mark)
    assert model is not None
    return model.matches(code_tokens(title))


def test_model_codes_compare_whole() -> None:
    # Русские буквы вместо латинских, дефисы, точки и пробелы внутри кода — та же модель.
    assert matches("по типу Масса-К TB-M-300.2-A3", "Весы ТВ-М-300.2-А3 напольные")
    assert matches("по типу Масса-К TB-M-300.2-A3", "Весы ТВ М 300.2 А3")
    assert matches("Casio Celviano AP-650M BK - чёрный или аналог", "Цифровое пианино Casio Celviano AP-650MBK")
    assert not matches("по типу Масса-К TB-M-300.2-A3", "Весы TB-M-150.2-A3")  # другая модель серии
    # Короткий номер — только с маркой и только целым словом.
    assert matches("Бирюса 110 или аналог", "Холодильник Бирюса 110")
    assert not matches("Бирюса 110 или аналог", "Холодильник Атлант 110 л")
    assert not matches("Бирюса 110 или аналог", "Холодильник Бирюса 1100")


def test_model_query() -> None:
    assert reference_model("по типу Polair CM107-S").query("шкаф") == "шкаф Polair CM107-S"
    assert reference_model("Бирюса 110").query("бирюса") == "Бирюса 110"  # слово уже в модели — не повторяем
