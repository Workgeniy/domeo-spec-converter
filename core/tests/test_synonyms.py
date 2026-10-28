from __future__ import annotations

from app.pricing.history import analyze_name, tokens


def test_word_forms_are_one_word() -> None:
    # Падежи и числа: «Стеллаж перфорированный» теперь внутри «Стеллаж с перфорированными полками».
    assert tokens("Стеллаж перфорированный") <= tokens("Стеллаж с перфорированными полками")
    assert tokens("Стол для воспитателя, ЛДСП") == tokens("столы воспитателей лдсп")
    # Беглая гласная: котел/котла, полок/полка.
    assert tokens("Котел пищеварочный") == tokens("котла пищеварочного")
    assert tokens("Полка") == tokens("полок")


def test_dictionary() -> None:
    assert tokens("Электроплита") == tokens("Плита электрическая")
    assert tokens("Ванна моечная двухсекционная") == tokens("Мойка двухсекционная")
    assert tokens("Печь СВЧ") == tokens("Микроволновая печь")
    assert tokens("ПММ фронтальная") == tokens("Посудомоечная машина фронтальная")
    assert tokens("Столик журнальный") == tokens("Стол журнальный")
    assert tokens("Полка навесная") == tokens("Полка настенная")
    assert tokens("Мойка нерж.") == tokens("Мойка нержавеющая")
    assert tokens("Водоумягчитель") == tokens("Смягчитель воды")
    assert tokens("Кукольная коляска") == tokens("Коляска для кукол")  # прилагательное ↔ своё слово


def test_different_words_stay_different() -> None:
    assert not tokens("Видеокамера") & tokens("Камера холодильная")
    assert tokens("Столешница") != tokens("Стол")
    assert not tokens("Холодильник") & tokens("Шкаф холодильный")
    assert tokens("Дверь") != tokens("Двор")
    assert tokens("Шкаф для белья") != tokens("Шкаф белый")  # стеммер сам склеил бы «белья» и «белый»
    assert tokens("Электронные весы") != tokens("Весы электрические")
    assert tokens("Polair CM107-S") == {"polair", "cm107"}  # марки и модели — как есть


def test_head_noun() -> None:
    assert analyze_name("Шкаф холодильный").head == analyze_name("Холодильный шкаф").head != ""
    assert analyze_name("Обеденный стол с 4 стульями").head == analyze_name("Стол").head
    assert analyze_name("Стул для обеденного стола").head != analyze_name("Обеденный стол с 4 стульями").head
    assert analyze_name("Polair CM107-S, шкаф").head == ""  # марка первой — главное слово не определяем
    assert analyze_name("Стулья с пюпитром").head_word == "стулья" and analyze_name("Рулонная штора").head_word == "штора"
