"""Сопоставление позиций спецификации с прайсом закупки.

Три уровня, от строгого к нестрогому: точное совпадение нормализованного наименования;
нестрогое — по общим значимым словам (индекс слово → позиции прайса, оценка по доле общих
слов и совпадению начала); аналог — лучший кандидат с низкой оценкой, помечается отдельно,
чтобы оператор видел, что это не та же позиция. Что ниже порога — «не найдено».

Слова сравниваются основами и через словарь (synonyms.py). Кроме нашего наименования
позиция находится и по тому, как её называли поставщики (номенклатура партнёра в истории
закупок): в проекте могут написать «Смягчитель воды DVA LT16», а у нас это «Водоумягчитель
для пароконвектомата». Эти же названия идут в поиск цен на рынке (``market_names``).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from typing import NamedTuple

from ..models import HistoryCandidate, HistoryPrice, HistoryPurchase, MatchKind
from .history import analyze_name, normalize_name
from .pricelist import PriceEntry, PriceList

FUZZY_THRESHOLD = 0.6  # оценка, начиная с которой считаем, что это та же позиция
ANALOG_THRESHOLD = 0.3  # ниже — не показываем даже как аналог
PURCHASES_SHOWN = 10  # сколько последних покупок лучшего кандидата отдаём оператору
ALIAS_LIMIT = 5  # сколько названий у поставщиков на позицию участвуют в сопоставлении
ALIAS_SCORE_CAP = 0.95  # совпадение по названию у поставщика не выше, чем по нашему
KIT_PREFIX = "комплект:"  # покупка комплектом сборки — названия у поставщика нет
# Пометки учёта в конце номенклатуры партнёра: «(Астра)», «(ЛС)», «(2)», оборванное «(Холанд», «*».
PARTNER_TAIL = re.compile(r"\s*(?:\((?:[A-Za-zА-Яа-яЁё .-]{1,24}|\d{1,2})\)|\([A-Za-zА-Яа-яЁё .-]{1,24}|\*+)\s*$")

Ranked = tuple[PriceEntry, float, str]  # позиция прайса, оценка, название у поставщика (если совпало по нему)


class Alias(NamedTuple):
    """Название позиции у поставщика из истории закупок."""

    name: str
    key: str
    tokens: set[str]
    head: str
    loose: set[str]


def clean_partner_name(text: str) -> str:
    """Номенклатура партнёра без пометок учёта в конце."""
    name = " ".join(str(text or "").split())
    while True:
        stripped = PARTNER_TAIL.sub("", name).rstrip(" .,;")
        if stripped == name:
            return name
        name = stripped


def aliases_of(entry: PriceEntry, limit: int = ALIAS_LIMIT) -> list[str]:
    """Как позицию называли поставщики — по покупкам из истории, частые первыми (при равенстве —
    свежие). Комплекты сборок и название, совпадающее с нашим, не в счёт."""
    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    for purchase in entry.purchases:  # покупки лежат от новых к старым
        if not purchase.partner_item or purchase.partner_item.startswith(KIT_PREFIX):
            continue
        name = clean_partner_name(purchase.partner_item)
        key = normalize_name(name)
        if not key or key == entry.key:
            continue
        counts[key] += 1
        names.setdefault(key, name)
    return [names[key] for key, _ in counts.most_common(limit)]


class Matcher:
    def __init__(self, price_list: PriceList):
        self.by_key = price_list.by_key()
        self.index: dict[str, set[str]] = defaultdict(set)
        self.entry_tokens: dict[str, set[str]] = {}
        self.entry_heads: dict[str, str] = {}
        self.entry_aliases: dict[str, list[Alias]] = {}
        for entry in price_list.entries:
            info = analyze_name(entry.name)
            self.entry_tokens[entry.key] = set(info.stems)
            self.entry_heads[entry.key] = info.head
            for t in info.stems:
                self.index[t].add(entry.key)
            aliases = []
            for name in aliases_of(entry):
                alias_info = analyze_name(name)
                aliases.append(Alias(name, alias_info.key, set(alias_info.stems), alias_info.head, alias_info.loose))
                for t in alias_info.stems:
                    self.index[t].add(entry.key)
            if aliases:
                self.entry_aliases[entry.key] = aliases

    def match(self, name: str, description: str = "") -> HistoryPrice:
        key = normalize_name(name)
        exact = self.by_key.get(key)
        if exact is not None:
            return self._result("exact", [(exact, 1.0, "")])

        info = analyze_name(name)
        query_tokens = set(info.stems)
        head = info.head
        scored: dict[str, tuple[float, str]] = {}
        for t in query_tokens:
            for entry_key in self.index.get(t, ()):
                if entry_key not in scored:
                    scored[entry_key] = self._best_score(key, query_tokens, head, entry_key)
        # При равной оценке вперёд — позиция с большим числом закупок: её цены надёжнее.
        best = sorted(scored.items(), key=lambda kv: (-kv[1][0], -self.by_key[kv[0]].count, kv[0]))[:5]
        ranked = [(self.by_key[k], score, alias) for k, (score, alias) in best if score >= ANALOG_THRESHOLD]
        if not ranked:
            return HistoryPrice(kind="none", matched_at=date.today().isoformat())
        kind: MatchKind = "fuzzy" if ranked[0][1] >= FUZZY_THRESHOLD else "analog"
        return self._result(kind, ranked)

    def market_names(self, name: str, description: str = "", limit: int = 2) -> list[str]:
        """Названия той же позиции у поставщиков по истории — для поиска цены на рынке: у
        поставщика это обычно конкретная модель. Только при уверенном совпадении (точно/похоже):
        по аналогу чужие модели искать незачем. Не берём названия общее нашего («Шкаф-сушка»
        при «Шкаф-сушка настенный» — поиск только расширится; с номером модели — берём) и с
        другим главным словом без единого общего слова с нашим («Контейнер полочный» у «Секции
        подвесной» — скорее деталь или замена, а не сама позиция)."""
        result = self.match(name, description)
        if result.kind not in ("exact", "fuzzy") or result.best is None:
            return []
        info = analyze_name(name)
        own = set(info.stems)
        names = [
            alias.name
            for alias in self.entry_aliases.get(result.best.key, ())
            if alias.key != info.key
            and (not alias.tokens <= own or any(ch.isdigit() for ch in alias.name))  # модель («СП-1») — уже не общее
            and (alias.loose & info.loose or not alias.head)  # марка с моделью («Polair CM107-S») — сама позиция
        ]
        return names[:limit]

    def _result(self, kind: MatchKind, ranked: list[Ranked]) -> HistoryPrice:
        candidates = [_candidate(entry, score, alias) for entry, score, alias in ranked]
        best_entry = ranked[0][0]
        purchases = [
            HistoryPurchase(
                purchased_at=p.purchased_at.isoformat() if p.purchased_at else None,
                unit_price=p.unit_price,
                qty=p.qty,
                partner_item=p.partner_item,
                order=p.order,
                outlier=p.outlier,
            )
            for p in best_entry.purchases[:PURCHASES_SHOWN]
        ]
        return HistoryPrice(kind=kind, best=candidates[0], candidates=candidates, purchases=purchases, matched_at=date.today().isoformat())

    def _best_score(self, key: str, query_tokens: set[str], head: str, entry_key: str) -> tuple[float, str]:
        """Лучшая оценка позиции: по нашему наименованию или по одному из названий у поставщиков."""
        own = _score(key, query_tokens, entry_key, self.entry_tokens[entry_key])
        best = (_head_capped(own, head, self.entry_heads[entry_key]), "")
        for alias in self.entry_aliases.get(entry_key, ()):
            if len(query_tokens & alias.tokens) < min(2, len(query_tokens)):
                continue  # одно общее слово с чужим названием («Сейф T-40.EL») — не повод
            # Без бонуса за общее начало: короткое общее название («Комплект мебели») иначе
            # перетягивало бы на себя всё, что с него начинается.
            score = min(ALIAS_SCORE_CAP, _score(key, query_tokens, alias.key, alias.tokens, prefix_bonus=False))
            score = _head_capped(score, head, alias.head)
            if score > best[0]:
                best = (score, alias.name)
        return best


def _score(key: str, query_tokens: set[str], candidate_key: str, candidate_tokens: set[str], prefix_bonus: bool = True) -> float:
    if not query_tokens or not candidate_tokens:
        return 0.0
    common = len(query_tokens & candidate_tokens)
    # Доля общих слов от запроса и от кандидата — чтобы длинный кандидат с одним общим
    # словом не побеждал, а короткий запрос внутри длинного имени — засчитывался.
    recall = common / len(query_tokens)
    precision = common / len(candidate_tokens)
    score = 0.65 * recall + 0.35 * precision
    if prefix_bonus and (candidate_key.startswith(key[:20]) or key.startswith(candidate_key[:20])):
        score = min(1.0, score + 0.15)  # общее начало — сильный признак той же позиции
    return round(score, 3)


def _head_capped(score: float, head: str, candidate_head: str) -> float:
    """Разные главные слова — не та же позиция, даже если слова те же: «Стул для обеденного
    стола» и «Стол обеденный с 4 стульями». Такой кандидат — не выше аналога."""
    if head and candidate_head and head != candidate_head:
        return min(score, round(FUZZY_THRESHOLD - 0.01, 3))
    return score


def _candidate(entry: PriceEntry, score: float, alias: str = "") -> HistoryCandidate:
    return HistoryCandidate(
        key=entry.key,
        name=entry.name,
        group=entry.group,
        score=score,
        alias=alias,
        price_min=entry.price_min,
        price_max=entry.price_max,
        price_median=entry.price_median,
        price_last=entry.price_last,
        last_date=entry.last_date.isoformat() if entry.last_date else None,
        purchases=entry.count,
        descriptions=entry.descriptions[:2],
    )
