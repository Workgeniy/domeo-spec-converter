"""Эталонная модель из графы «Тип, марка»: «по типу Polair CM107-S», «Бирюса 110 или аналог».

Проектировщик называет конкретный товар — по нему и ищем: запрос к поисковику по модели,
в индексе — предложения с тем же кодом модели. Коды сравниваются целиком, без дефисов,
точек и косых, а похожие русские и латинские буквы считаются одной (С/C, М/M, Т/T…): у
продавцов «ТВ-М-300.2-А3» и «TB-M-300.2-A3» — одна модель, «AP-650M BK» и «AP-650MBK» — тоже.
Запятая между цифрами — часть кода («КХН-6,43» не «КХН-6,61»), размер («800х1200») — не код.
Короткий код («110», «100С») сам по себе ничего не значит — тогда нужна ещё и марка
(«Бирюса», «Сибэст»), и совпасть он должен целиком. «… для КХН-6,61» — аксессуар к модели,
а не она сама.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .synonyms import stem

PREFIX = re.compile(r"^\s*(?:по\s+типу|типа|тип|марка|модель)(?![а-яa-z])\s*[:\-–—]?\s*", re.I)
SUFFIX = re.compile(r"[\s,;.(]*(?:или|либо)\s+(?:аналог|эквивалент)\w*\)?[\s.]*$|[\s,;(]*\(?\s*аналог\w*\s*\)?[\s.]*$", re.I)
NOT_MODEL = re.compile(r"^(?:гост|ту|сто|ост|снип|сп|серия)(?![а-яa-z])", re.I)  # обозначение документа, а не товар
DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")
SPLIT = re.compile(r"[\s,;()\[\]«»\"'*]+")
NOT_CODE_CHARS = re.compile(r"[^0-9a-zа-я]+")
DIMENSION = re.compile(r"^\d+(?:x\d+)+$")  # «800x1200», «1000x600x870» — размер, а не модель
# Русские буквы, которые пишут вместо похожих латинских (после перевода в строчные).
LOOKALIKE = str.maketrans("авекмнорстухё×", "abekmhopctyxex")
ACCESSORY_BEFORE = {"для", "пoд", "k", "ko"}  # «стеллаж для КХН-6,61», «подставка под …» (уже по LOOKALIKE)
# Уточнения после модели: «ШР-22-600 на подставке со скамьей» — это не голый ШР-22-600.
QUALIFIER = re.compile(r"(?<![а-яa-z])(?:на|со|с|без)\s+([а-я]{4,})")
MAX_JOIN = 4  # код у продавца может быть разбит пробелами: «AP-650M BK» ↔ «AP-650MBK»
LONG_CODE = 6  # с такой длины код может быть началом более длинного («CM107-S» в «CM107-SM»)


def code_tokens(text: str) -> tuple[str, ...]:
    """Слова текста как коды: строчные, без знаков внутри, похожие буквы — латиницей."""
    text = DECIMAL_COMMA.sub("", (text or "").lower().translate(LOOKALIKE))
    tokens = (NOT_CODE_CHARS.sub("", t) for t in SPLIT.split(text))
    return tuple(t for t in tokens if t)


def _strong(token: str) -> bool:
    has_digit = any(c.isdigit() for c in token)
    has_letter = any(c.isalpha() for c in token)
    return has_digit and ((has_letter and len(token) >= 4) or len(token) >= 5)


def find_code(tokens: tuple[str, ...], code: str) -> int:
    """Номер слова, с которого начинается код (возможно, склеенный из нескольких слов подряд),
    или -1. Короткий код — только целиком, длинный — может быть началом («CM107-S» в «CM107-SM»)."""
    for i in range(len(tokens)):
        joined = ""
        for token in tokens[i : i + MAX_JOIN]:
            joined += token
            if joined == code or (len(code) >= LONG_CODE and joined.startswith(code)):
                return i
            if not code.startswith(joined):
                break
    return -1


@dataclass(frozen=True)
class ModelRef:
    text: str  # как в проекте, без «по типу» и «или аналог»: «Polair CM107-S»
    code: str = ""  # главный код: «cm107s»
    weak: tuple[str, ...] = ()  # короткие коды: «110»
    words: tuple[str, ...] = ()  # слова марки: «бирюса»
    extra: tuple[str, ...] = ()  # основы уточнений: «на подставке со скамьей» — должны быть и у предложения

    def matches(self, tokens: tuple[str, ...]) -> bool:
        """Та же модель в названии предложения (``tokens`` — code_tokens названия)."""
        if self.code:
            at = find_code(tokens, self.code)
            if at < 0 or (at > 0 and tokens[at - 1] in ACCESSORY_BEFORE):
                return False
            # Короткий код без марки рядом ничего не значит: «100С» найдётся и в «100 см».
            return len(self.code) >= LONG_CODE or not self.words or any(w in tokens for w in self.words)
        if not self.weak or not self.words:
            return False  # ни кода, ни марки с номером — сравнивать не по чему
        # Короткий номер — только целым словом: «Бирюса 110» не «Бирюса 1100».
        return all(w in tokens for w in self.weak) and all(w in tokens for w in self.words)

    @property
    def probe(self) -> str:
        """Что должно быть в склеенном названии — быстрый отбор кандидатов."""
        return self.code or (self.weak[0] if self.weak else "")

    def query(self, head: str = "") -> str:
        """Запрос к поисковику: «шкаф Polair CM107-S» — главное слово наименования для
        контекста, если его нет в самой модели."""
        if head and head.lower() not in self.text.lower():
            return f"{head} {self.text}"
        return self.text


@lru_cache(maxsize=4096)
def reference_model(type_mark: str) -> ModelRef | None:
    """Эталон из графы «Тип, марка» или None, если там не товар (пусто, ГОСТ, «—», только размер)."""
    text = " ".join(str(type_mark or "").split())
    for _ in range(2):
        text = SUFFIX.sub("", PREFIX.sub("", text)).strip(" ,;.-–—")
    if not text or NOT_MODEL.match(text):
        return None
    tokens = [t for t in code_tokens(text) if not DIMENSION.match(t)]
    strong = [t for t in tokens if _strong(t)]
    weak = tuple(t for t in tokens if any(c.isdigit() for c in t) and not _strong(t))
    words = tuple(t for t in tokens if t.isalpha() and len(t) >= 3)
    if not strong and not (weak and words):
        return None
    extra = tuple(stem(w) for w in QUALIFIER.findall(text.lower().replace("ё", "е")))
    return ModelRef(text=text[:80], code=max(strong, key=len) if strong else "", weak=weak, words=words[:2], extra=extra)
