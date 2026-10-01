"""Параметры поиска цены, которые задаёт оператор: «Материал ножек: металл», «Цвет: серый»,
«Производитель: Abat», «Объём: 20 л».

Числовые (с единицами) идут туда же, куда параметры из характеристик (params.py). Текстовые
уходят в поисковый запрос и сверяются с названием предложения:

- материал и цвет — по словарю. «Металл» подтверждается и «нержавеющей сталью» (она частный
  случай), «нержавеющая сталь» просто «сталью» не подтверждается, но и не опровергается
  («не указано»), а «ЛДСП» вместо «металла» — противоречие;
- материал части изделия («Материал ножек») ищется рядом со словом «ножки» в названии; если
  ножки в названии не названы, противоречия нет — материал там может быть о столешнице;
- породы дерева рядом с ЛДСП и МДФ — это цвет декора («ЛДСП дуб сонома»), а не материал;
- остальное (производитель, тип, назначение) — по словам: все слова значения есть в
  названии — совпало, иначе «не указано».
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache

from ..models import SearchParam
from .history import normalize_name, stems
from .params import Params, compare_params, extract_params

MAX_PARAMS = 10
NAME_LIMIT = 60
VALUE_LIMIT = 120
MATCH, CONFLICT, UNKNOWN = "match", "conflict", "unknown"
MATERIAL, COLOUR, TEXT = "material", "colour", "text"
NEAR_WORDS = 2  # материал части изделия ищем не дальше двух слов от её названия

_B = r"(?<![а-яa-z0-9])"
_E = r"(?![а-яa-z0-9])"
_ADJ = r"(?:ый|ий|ой|ая|яя|ое|ее|ые|ие|ого|его|ому|ему|ым|им|ых|их|ыми|ими|ую|юю|о|е)"


@dataclass(frozen=True)
class Term:
    name: str
    parent: str  # более общее: нержавеющая сталь → сталь → металл
    pattern: re.Pattern[str]


def _vocabulary(rows: list[tuple[str, str, str]]) -> dict[str, Term]:
    return {name: Term(name, parent, re.compile(f"{_B}(?:{pattern}){_E}")) for name, pattern, parent in rows}


# Шаблоны — по тексту после normalize_name: строчные, ё→е, без знаков препинания.
MATERIALS = _vocabulary(
    [
        ("металл", r"металл\w*", ""),
        ("сталь", r"стал(?:ь|и|ью|ей|ьн\w*)", "металл"),
        ("нержавеющая сталь", r"нерж\w*(?:\s+стал\w*)?|aisi\s*\d{3}|inox", "сталь"),
        ("оцинкованная сталь", r"оцинк\w*(?:\s+стал\w*)?", "сталь"),
        ("алюминий", r"алюмини\w*", "металл"),
        ("хром", r"хром\w*", "металл"),
        ("чугун", r"чугун\w*", "металл"),
        ("дерево", r"дерев(?:о|а|у|ом|е|ья|ьев|ьями|ян\w*)|древесин\w*", ""),
        ("массив дерева", r"массив\w*", "дерево"),
        ("берёза", r"берез\w*", "дерево"),
        ("бук", r"бук(?:а|ом|е|ов\w*)?", "дерево"),
        ("дуб", r"дуб(?:а|ом|е|ов\w*)?", "дерево"),
        ("сосна", r"сосн\w*", "дерево"),
        ("ясень", r"ясен(?:ь|я|ем|е)?|ясн(?:я|ем|е)", "дерево"),
        ("ольха", r"ольх\w*", "дерево"),
        ("орех", r"орех(?:а|ом|ов\w*)?", "дерево"),
        ("ДСП", r"дсп", ""),
        ("ЛДСП", r"лдсп|ламинированн\w*\s+дсп", "ДСП"),
        ("МДФ", r"л?мдф", ""),
        ("ХДФ", r"хдф|двп", ""),
        ("фанера", r"фанер\w*", ""),
        ("пластик", r"пластик\w*|пластмасс\w*", ""),
        ("полипропилен", r"полипропилен\w*", "пластик"),
        ("ПВХ", r"пвх", "пластик"),
        ("поликарбонат", r"поликарбонат\w*", "пластик"),
        ("акрил", r"акрил\w*", "пластик"),
        ("стекло", r"стекл\w*", ""),
        ("камень", r"камен\w*|камн\w*", ""),
        ("искусственный камень", r"(?:искусственн|акрилов|кварцев)\w*\s+(?:камен\w*|камн\w*)", "камень"),
        ("мрамор", r"мрамор\w*", "камень"),
        ("гранит", r"гранит\w*", "камень"),
        ("керамогранит", r"керамогранит\w*", "камень"),
        ("керамика", r"керамик\w*|керамич\w*", ""),
        ("ткань", r"ткан\w*|текстил\w*", ""),
        ("велюр", r"велюр\w*", "ткань"),
        ("рогожка", r"рогожк\w*", "ткань"),
        ("флок", r"флок\w*", "ткань"),
        ("микрофибра", r"микрофибр\w*", "ткань"),
        ("кожа", r"кож(?:а|и|ей|у|ан\w*)", ""),
        ("экокожа", r"экокож\w*|эко\s+кож\w*|кожзам\w*|(?:искусственн\w*|иск)\s+кож\w*|винилискож\w*", ""),
    ]
)
COLOURS = _vocabulary(
    [
        ("белый", rf"бел{_ADJ}", ""),
        ("чёрный", rf"черн{_ADJ}", ""),
        ("серый", rf"сер{_ADJ}", ""),
        ("серебристый", r"серебрист\w*|серебрян\w*", ""),
        ("бежевый", r"беж\w*", ""),
        ("коричневый", r"коричнев\w*", ""),
        ("красный", rf"красн{_ADJ}", ""),
        ("бордовый", r"бордов\w*", ""),
        ("синий", r"син(?:ий|яя|ее|ие|его|ей|ему|им|их|ими|юю)", ""),
        ("голубой", rf"голуб{_ADJ}", ""),
        ("зелёный", rf"зелен{_ADJ}", ""),
        ("жёлтый", rf"желт{_ADJ}", ""),
        ("оранжевый", rf"оранжев{_ADJ}", ""),
        ("розовый", rf"розов{_ADJ}", ""),
        ("фиолетовый", rf"фиолетов{_ADJ}", ""),
        ("бирюзовый", rf"бирюзов{_ADJ}", ""),
        ("графит", r"графит\w*", ""),
        ("венге", r"венге", ""),
        ("слоновая кость", r"слонов\w*\s+кост\w*", ""),
        ("бук", r"бук(?:а|ом|е|ов\w*)?", ""),
        ("дуб", r"дуб(?:а|ом|е|ов\w*)?", ""),
        ("дуб сонома", r"(?:дуб\w*\s+)?сонома", "дуб"),
        ("орех", r"орех(?:а|ом|ов\w*)?", ""),
        ("ольха", r"ольх\w*", ""),
        ("ясень", r"ясен(?:ь|я|ем|е)?|ясн(?:я|ем|е)", ""),
        ("вишня", r"вишн\w*", ""),
        ("клён", r"клен\w*", ""),
    ]
)
VOCABULARIES = {MATERIAL: MATERIALS, COLOUR: COLOURS}
BOARDS = {"ДСП", "ЛДСП", "МДФ", "ХДФ"}
WOOD_SPECIES = {name for name, term in MATERIALS.items() if term.parent == "дерево" and name != "массив дерева"}

# Части изделия: у «Материал ножек: металл» материал ищется рядом с ними.
PARTS = {
    name: re.compile(f"{_B}(?:{pattern}){_E}")
    for name, pattern in {
        "ножки": r"ножк\w*|ножек|опор\w*",
        "каркас": r"(?:металло)?каркас\w*|рам(?:а|ы|е|ой|у)",
        "столешница": r"столешниц\w*",
        "корпус": r"корпус\w*",
        "фасад": r"фасад\w*",
        "обивка": r"обивк\w*|обит\w*",
        "сиденье": r"сидень\w*|сиден(?:ие|ия|ий|ии)",
        "спинка": r"спинк\w*",
        "дверцы": r"дверц\w*|двер(?:ь|и|ью|ей|ями)",
        "полки": r"полк(?:а|и|ой|у|е|ами|ах)|полок|полочк\w*",
        "ручки": r"ручк\w*|ручек",
        "мойка": r"мойк\w*|чаш(?:а|и|ей|у)",
    }.items()
}
COLOUR_KEY = re.compile(r"цвет|оттен|декор|окрас")
MATERIAL_KEY = re.compile(r"материал|обивк|покрыт|отделк")


def _ancestors(vocabulary: dict[str, Term]) -> dict[str, frozenset[str]]:
    result: dict[str, frozenset[str]] = {}
    for name in vocabulary:
        chain: set[str] = set()
        parent = vocabulary[name].parent
        while parent and parent not in chain:
            chain.add(parent)
            parent = vocabulary[parent].parent
        result[name] = frozenset(chain)
    return result


ANCESTORS = {kind: _ancestors(vocabulary) for kind, vocabulary in VOCABULARIES.items()}


@dataclass(frozen=True)
class Found:
    term: str
    start: int  # номер первого слова
    end: int  # номер последнего слова


@lru_cache(maxsize=65_536)
def find_terms(norm: str, kind: str) -> tuple[Found, ...]:
    """Термины словаря в тексте после normalize_name; из пересекающихся — самый длинный
    («нержавеющая сталь», а не «сталь» внутри неё)."""
    spans = [(m.start(), m.end(), term.name) for term in VOCABULARIES[kind].values() for m in term.pattern.finditer(norm)]
    spans.sort(key=lambda s: (s[0] - s[1], s[0]))
    taken: list[tuple[int, int, str]] = []
    for start, end, name in spans:
        if not any(start < e and s < end for s, e, _ in taken):
            taken.append((start, end, name))
    return tuple(Found(name, norm.count(" ", 0, start), norm.count(" ", 0, end)) for start, end, name in sorted(taken))


@lru_cache(maxsize=65_536)
def find_parts(norm: str) -> tuple[tuple[str, int], ...]:
    """(часть изделия, номер слова) по тексту после normalize_name."""
    return tuple((name, norm.count(" ", 0, m.start())) for name, pattern in PARTS.items() for m in pattern.finditer(norm))


@dataclass(frozen=True)
class Wanted:
    """Текстовый параметр оператора, готовый к сверке с названием предложения."""

    label: str  # «материал ножек — металл»
    kind: str  # material | colour | text
    terms: tuple[str, ...] = ()  # термины словаря (материал, цвет)
    part: str = ""  # часть изделия («ножки»)
    words: tuple[str, ...] = ()  # основы слов значения (для остального)
    query: str = ""  # слова для поисковика: «ножки металл»


@dataclass
class ManualParams:
    """Параметры оператора по позиции, разобранные для поиска."""

    items: list[SearchParam] = field(default_factory=list)
    wanted: list[Wanted] = field(default_factory=list)
    numeric_text: str = ""  # «20 л 1200х600 мм» — числа с единицами
    required: Params | None = None  # они же, разобранные

    def empty(self) -> bool:
        return not self.items

    def checkable(self) -> bool:
        """Есть что сверять с предложениями (а не только слова, которые ни во что не разобрались)."""
        return bool(self.wanted) or (self.required is not None and not self.required.empty())

    def query(self) -> str:
        return " ".join(w.query for w in self.wanted if w.query)

    def describe(self) -> str:
        return "; ".join(_label(p) for p in self.items)


def clean_params(params: Iterable[SearchParam] | None) -> list[SearchParam]:
    """Без пустых значений и повторов, в разумных пределах длины и числа."""
    result: list[SearchParam] = []
    seen: set[tuple[str, str]] = set()
    for param in params or ():
        name = " ".join(param.name.split())[:NAME_LIMIT]
        value = " ".join(param.value.split())[:VALUE_LIMIT]
        key = (name.lower(), value.lower())
        if value and key not in seen:
            seen.add(key)
            result.append(SearchParam(name=name, value=value))
        if len(result) >= MAX_PARAMS:
            break
    return result


def params_key(params: Iterable[SearchParam] | None) -> str:
    """Ключ для кэша: порядок и регистр не важны."""
    return "; ".join(sorted(f"{normalize_name(p.name)}={normalize_name(p.value)}" for p in clean_params(params)))


def parse_params(params: Iterable[SearchParam] | None) -> ManualParams:
    items = clean_params(params)
    wanted: list[Wanted] = []
    numeric: list[str] = []
    for param in items:
        has_numbers = not extract_params(param.value).empty()
        if has_numbers:
            numeric.append(param.value)
        item = _wanted(param, has_numbers)
        if item is not None:
            wanted.append(item)
    numeric_text = " ".join(numeric)
    return ManualParams(items=items, wanted=wanted, numeric_text=numeric_text, required=extract_params(numeric_text) if numeric_text else None)


def _label(param: SearchParam) -> str:
    if not param.name:
        return param.value
    return f"{param.name[:1].lower()}{param.name[1:]} — {param.value}"


def _wanted(param: SearchParam, has_numbers: bool) -> Wanted | None:
    key = normalize_name(param.name)
    value = normalize_name(param.value)
    part = next((name for name, pattern in PARTS.items() if pattern.search(key)), "")
    if COLOUR_KEY.search(key):
        kind = COLOUR
    elif MATERIAL_KEY.search(key) or part:
        kind = MATERIAL
    elif find_terms(value, MATERIAL):
        kind = MATERIAL
    elif find_terms(value, COLOUR):
        kind = COLOUR
    else:
        kind = TEXT
    terms = tuple(dict.fromkeys(f.term for f in find_terms(value, kind))) if kind != TEXT else ()
    if kind != TEXT and terms:
        return Wanted(label=_label(param), kind=kind, terms=terms, part=part, query=f"{part} {param.value}" if part else param.value)
    if has_numbers:
        return None  # «20 л», «2 кВт» — числовой параметр, сверяется по числам
    words = tuple(stems(param.value))
    if not words:
        return None
    return Wanted(label=_label(param), kind=TEXT, words=words, query=param.value)


def _has_word(word: str, offer_words: set[str]) -> bool:
    return word in offer_words or (len(word) >= 4 and any(w.startswith(word) for w in offer_words))


def _near(found: list[Found], positions: list[int], part_words: set[int]) -> list[Found]:
    """Термины у названия части изделия: в том же слове («металлокаркас»), потом после него
    («ножки металлические»), потом перед ним («на металлических ножках»), не дальше NEAR_WORDS
    и не перескакивая через другую часть («столешница ЛДСП, ножки металл»)."""
    result: list[Found] = []
    for p in positions:
        hits = [f for f in found if f.start <= p <= f.end]
        for step in (1, -1):
            if hits:
                break
            for distance in range(1, NEAR_WORDS + 1):
                i = p + step * distance
                if i in part_words:
                    break
                hits = [f for f in found if (f.start if step > 0 else f.end) == i]
                if hits:
                    break
        result += hits
    return result


def check(wanted: Wanted, norm: str, offer_words: set[str]) -> str:
    """Совпало / противоречит / не указано — для одного параметра и названия предложения
    (``norm`` — после normalize_name, ``offer_words`` — его основы)."""
    if wanted.kind == TEXT:
        return MATCH if all(_has_word(w, offer_words) for w in wanted.words) else UNKNOWN
    found = list(find_terms(norm, wanted.kind))
    if wanted.kind == MATERIAL and any(f.term in BOARDS for f in found):
        found = [f for f in found if f.term not in WOOD_SPECIES]  # «ЛДСП дуб сонома» — дуб тут цвет
    may_conflict = True
    if wanted.part:
        parts = find_parts(norm)
        positions = [i for name, i in parts if name == wanted.part]
        if positions:
            found = _near(found, positions, {i for _, i in parts})
        else:
            may_conflict = False  # часть не названа — материал в названии может быть о другой части
    names = {f.term for f in found}
    ancestors = ANCESTORS[wanted.kind]
    satisfied = [w for w in wanted.terms if any(t == w or w in ancestors[t] for t in names)]
    if len(satisfied) == len(wanted.terms):
        return MATCH
    if satisfied or not names or not may_conflict:
        return UNKNOWN
    if any(t in ancestors[w] for t in names for w in wanted.terms):
        return UNKNOWN  # в названии общее слово («сталь»), а нужно частное («нержавеющая сталь»)
    return CONFLICT


@dataclass(frozen=True)
class Verdict:
    matches: int = 0  # по текстовым параметрам
    conflicts: int = 0
    missing: int = 0
    confirmed: bool = False  # подтверждены все параметры оператора — и текстовые, и числовые


def compare_manual(manual: ManualParams, norm: str, offer_words: set[str], offer_params: Params) -> Verdict:
    """Сверка параметров оператора с предложением. Счётчики — по текстовым (числовые считаются
    вместе с параметрами из характеристик, params.compare_params), «подтверждено» — по всем."""
    matches = conflicts = missing = 0
    for wanted in manual.wanted:
        status = check(wanted, norm, offer_words)
        matches += status == MATCH
        conflicts += status == CONFLICT
        missing += status == UNKNOWN
    numbers_ok = True
    if manual.required is not None and not manual.required.empty():
        m, c, x = compare_params(manual.required, offer_params)
        numbers_ok = m > 0 and not c and not x
    confirmed = manual.checkable() and not conflicts and not missing and numbers_ok
    return Verdict(matches, conflicts, missing, confirmed)
