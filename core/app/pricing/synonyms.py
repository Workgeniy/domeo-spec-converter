"""Словарь сопоставления наименований: словоформы, обороты, сокращения.

Одно и то же в проекте, в истории закупок и в каталоге магазина пишут по-разному:
«стеллаж перфорированный» и «стеллаж с перфорированными полками», «электроплита» и
«плита электрическая», «ванна моечная» и «мойка». ``canonical_stems`` сводит слова
наименования к общим основам:

1. слово — к основе русским стеммером Snowball (падежи, числа, роды);
2. беглая гласная убирается (котел/котла, полок/полка → котл, полк);
3. сокращения и уменьшительные — к основному слову (``WORDS``: нерж → нержавеющий,
   столик → стол);
4. составное «электро…» — в «… электрический», обороты — в одно слово (``PHRASES``:
   ванна моечная → мойка).

Словарь короткий намеренно: сюда попадает только то, что везде значит одно и то же.
История закупок даёт соответствия целыми наименованиями (наша номенклатура ↔ номенклатура
поставщика, см. ``matching.aliases_of``), а не пословно: пословно она путает «видеокамеру»
с «камерой холодильной» и «стол» со «столешницей».
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable
from functools import lru_cache

import snowballstemmer

RUSSIAN_WORD = re.compile(r"[а-я]+")
ADJECTIVE_END = re.compile(r"(?:ый|ий|ой|ая|яя|ое|ее|ые|ие)$")  # «Рулонная штора»: первое слово — не главное
VOWELS = frozenset("аеиоуыэюя")
ELECTRO = "электро"
ELECTRO_KEEP = ("электрон", "электрод")  # электронный, электроды — не «электрический»
# Где стеммер склеивает разные слова: у него «белья» и «белый» — одна основа «бел».
FIXED_PREFIXES = {"бель": "бель"}  # белье, белья, бельевой

# Сокращения, уменьшительные и разные написания одного слова → основное слово.
WORDS: dict[str, str] = {
    "нерж": "нержавеющий",
    "нержавейка": "нержавеющий",
    "оцинк": "оцинкованный",
    "электр": "электрический",
    "навесной": "настенный",
    "столик": "стол",
    "стульчик": "стул",
    "шкафчик": "шкаф",
    "полочка": "полка",
    "тумбочка": "тумба",
    "табуретка": "табурет",
    "скамейка": "скамья",
    "кроватка": "кровать",
    "стаканчик": "стакан",
    "сковородка": "сковорода",
    "куллер": "кулер",
    "умягчитель": "смягчитель",
}

# Обороты и слова → как их пишут чаще. Порядок слов в обороте не важен.
PHRASES: dict[str, str] = {
    "ванна моечная": "мойка",
    "машина картофелеочистительная": "картофелечистка",
    "машина овощерезательная": "овощерезка",
    "машина тестомесильная": "тестомес",
    "печь пароконвекционная": "пароконвектомат",
    "свч": "печь микроволновая",
    "микроволновка": "печь микроволновая",
    "пмм": "машина посудомоечная",
    "посудомойка": "машина посудомоечная",
    "умывальник": "раковина",
    "рукомойник": "раковина",
    "водоумягчитель": "смягчитель воды",
}

_local = threading.local()  # стеммер Snowball хранит состояние — у каждого потока свой


def _stemmer() -> snowballstemmer.stemmer:
    stemmer = getattr(_local, "stemmer", None)
    if stemmer is None:
        stemmer = _local.stemmer = snowballstemmer.stemmer("russian")
    return stemmer


def _raw_stem(word: str) -> str:
    return _stemmer().stemWord(word) if RUSSIAN_WORD.fullmatch(word) else word


def _fold(stem: str) -> str:
    """Беглая гласная: «котел»/«котл», «полок»/«полк», «уровен»/«уровн» — одна основа.
    Короткие основы не трогаем: «двер» и «двор» должны остаться разными."""
    if len(stem) >= 5 and stem[-1] in "клнрц" and stem[-2] in "ео" and stem[-3] not in VOWELS:
        return stem[:-2] + stem[-1]
    return stem


_WORD_STEMS = {_raw_stem(word): _raw_stem(main) for word, main in WORDS.items()}


@lru_cache(maxsize=100_000)
def stem(word: str) -> str:
    """Основа слова, уже приведённого normalize_name (строчные, ё→е). Латиница, числа,
    артикулы — как есть."""
    if not RUSSIAN_WORD.fullmatch(word):
        return word
    for prefix, fixed in FIXED_PREFIXES.items():
        if word.startswith(prefix):
            return fixed
    base = _raw_stem(word)
    return _fold(_WORD_STEMS.get(base, base))


ELECTRIC = stem("электрический")


def _word_stems(word: str) -> tuple[str, ...]:
    """Составное «электроплита» — это «плита электрическая»."""
    rest = word[len(ELECTRO):]
    if word.startswith(ELECTRO) and len(rest) >= 4 and not word.startswith(ELECTRO_KEEP):
        return (stem(rest), ELECTRIC)
    return (stem(word),)


def _phrase_rules() -> list[tuple[frozenset[str], tuple[str, ...]]]:
    rules = [
        (frozenset(s for w in source.split() for s in _word_stems(w)), tuple(s for w in target.split() for s in _word_stems(w)))
        for source, target in PHRASES.items()
    ]
    return sorted(rules, key=lambda rule: -len(rule[0]))  # длинные обороты — раньше


_PHRASE_RULES = _phrase_rules()


def plain_stems(words: Iterable[str]) -> set[str]:
    """Основы слов без замены оборотов: «машина овощерезательная» остаётся «машин» и
    «овощерезательн» — чтобы видеть общие слова с «машина протирочно-резательная»."""
    return {s for word in words for s in _word_stems(word)}


def canonical_stems(words: Iterable[str]) -> list[str]:
    """Основы значимых слов наименования по порядку, без повторов, после словаря: одно и то
    же, написанное по-разному, даёт один набор. Оборот встаёт на место своего первого слова —
    первая основа остаётся «главным словом» наименования."""
    stems: list[str] = []
    for word in words:
        for s in _word_stems(word):
            if s not in stems:
                stems.append(s)
    for source, target in _PHRASE_RULES:
        if source.issubset(stems):
            replaced: list[str] = []
            for s in stems:
                for t in target if s in source else (s,):
                    if t not in replaced:
                        replaced.append(t)
            stems = replaced
    return stems
