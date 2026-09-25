"""Сопоставление позиций спецификации с прайсом закупки.

Три уровня, от строгого к нестрогому: точное совпадение нормализованного наименования;
нестрогое — по общим значимым словам (индекс слово → позиции прайса, оценка по доле общих
слов и совпадению начала); аналог — лучший кандидат с низкой оценкой, помечается отдельно,
чтобы оператор видел, что это не та же позиция. Что ниже порога — «не найдено».
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from ..models import HistoryCandidate, HistoryPrice, HistoryPurchase, MatchKind
from .history import normalize_name, tokens
from .pricelist import PriceEntry, PriceList

FUZZY_THRESHOLD = 0.6  # оценка, начиная с которой считаем, что это та же позиция
ANALOG_THRESHOLD = 0.3  # ниже — не показываем даже как аналог
PURCHASES_SHOWN = 10  # сколько последних покупок лучшего кандидата отдаём оператору


class Matcher:
    def __init__(self, price_list: PriceList):
        self.by_key = price_list.by_key()
        self.index: dict[str, set[str]] = defaultdict(set)
        self.entry_tokens: dict[str, set[str]] = {}
        for entry in price_list.entries:
            toks = tokens(entry.name)
            self.entry_tokens[entry.key] = toks
            for t in toks:
                self.index[t].add(entry.key)

    def match(self, name: str, description: str = "") -> HistoryPrice:
        key = normalize_name(name)
        exact = self.by_key.get(key)
        if exact is not None:
            return self._result("exact", [(exact, 1.0)])

        query_tokens = tokens(name)
        scored: dict[str, float] = {}
        for t in query_tokens:
            for entry_key in self.index.get(t, ()):
                if entry_key not in scored:
                    scored[entry_key] = self._score(key, query_tokens, entry_key)
        ranked = [(self.by_key[k], s) for k, s in sorted(scored.items(), key=lambda kv: kv[1], reverse=True)[:5] if s >= ANALOG_THRESHOLD]
        if not ranked:
            return HistoryPrice(kind="none", matched_at=date.today().isoformat())
        kind: MatchKind = "fuzzy" if ranked[0][1] >= FUZZY_THRESHOLD else "analog"
        return self._result(kind, ranked)

    def _result(self, kind: MatchKind, ranked: list[tuple[PriceEntry, float]]) -> HistoryPrice:
        candidates = [_candidate(entry, score) for entry, score in ranked]
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

    def _score(self, key: str, query_tokens: set[str], entry_key: str) -> float:
        entry_tokens = self.entry_tokens[entry_key]
        if not query_tokens or not entry_tokens:
            return 0.0
        common = len(query_tokens & entry_tokens)
        # Доля общих слов от запроса и от кандидата — чтобы длинный кандидат с одним общим
        # словом не побеждал, а короткий запрос внутри длинного имени — засчитывался.
        recall = common / len(query_tokens)
        precision = common / len(entry_tokens)
        score = 0.65 * recall + 0.35 * precision
        if entry_key.startswith(key[:20]) or key.startswith(entry_key[:20]):
            score = min(1.0, score + 0.15)  # общее начало — сильный признак той же позиции
        return round(score, 3)


def _candidate(entry: PriceEntry, score: float) -> HistoryCandidate:
    return HistoryCandidate(
        key=entry.key,
        name=entry.name,
        group=entry.group,
        score=score,
        price_min=entry.price_min,
        price_max=entry.price_max,
        price_median=entry.price_median,
        price_last=entry.price_last,
        last_date=entry.last_date.isoformat() if entry.last_date else None,
        purchases=entry.count,
        descriptions=entry.descriptions[:2],
    )
