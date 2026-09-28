"""Индексация цен к дате поставки.

Ставка в процентах за год по разделу берётся оператором из трёх источников: ответ
поставщика, официальный индекс или своя история закупок. Историю считаем сами: для каждой
позиции — медианная цена по годам, отсюда изменение год к году; по группе — медиана таких
изменений (так один подорожавший товар не тянет всю группу). Ставка группы — по объединённым
изменениям за последние три пары лет; если сравнений меньше десяти — ставки нет, берётся
общая. Цена к дате: base × (1 + ставка/100) ^ (лет до даты), доля года — по дням.
"""

from __future__ import annotations

import json
import os
import threading
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

from ..models import HistoryIndexation, IndexationGroup, IndexationPair, IndexationRate
from .pricelist import PriceList

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / ".data"
MOSCOW = ZoneInfo("Europe/Moscow")

MIN_SAMPLES = 10  # меньше сравнений — ставка по группе не считается
RECENT_PAIRS = 3  # сколько последних пар лет входит в ставку
RATIO_MIN, RATIO_MAX = 0.2, 5.0  # изменение цены вне этого коридора — не индексация, а другой товар


def year_ratios(price_list: PriceList) -> dict[str, dict[tuple[int, int], list[float]]]:
    """группа → (год, следующий год) → изменения цены одних и тех же позиций."""
    result: dict[str, dict[tuple[int, int], list[float]]] = defaultdict(lambda: defaultdict(list))
    for entry in price_list.entries:
        by_year: dict[int, list[float]] = defaultdict(list)
        for purchase in entry.purchases:
            if purchase.purchased_at is None or purchase.outlier or purchase.unit_price <= 0:
                continue
            by_year[purchase.purchased_at.year].append(purchase.unit_price)
        years = sorted(by_year)
        for a, b in zip(years, years[1:]):
            if b - a != 1:
                continue
            ratio = median(by_year[b]) / median(by_year[a])
            if RATIO_MIN < ratio < RATIO_MAX:
                result[entry.group or "—"][(a, b)].append(ratio)
    return result


def _group_stats(name: str, pairs: dict[tuple[int, int], list[float]], latest_year: int) -> IndexationGroup:
    recent: list[float] = []
    described: list[IndexationPair] = []
    for (a, b), ratios in sorted(pairs.items()):
        if len(ratios) >= 5:
            described.append(IndexationPair(years=f"{a}→{b}", rate=round((median(ratios) - 1) * 100, 1), samples=len(ratios)))
        if b > latest_year - RECENT_PAIRS:
            recent += ratios
    rate = round((median(recent) - 1) * 100, 1) if len(recent) >= MIN_SAMPLES else None
    return IndexationGroup(group=name, rate=rate, samples=len(recent), pairs=described)


def history_indexation(price_list: PriceList, today: date | None = None) -> HistoryIndexation:
    ratios = year_ratios(price_list)
    if not ratios:
        return HistoryIndexation(computed_at=(today or date.today()).isoformat())
    latest_year = max(b for pairs in ratios.values() for (_, b) in pairs)
    groups = [_group_stats(group, pairs, latest_year) for group, pairs in ratios.items()]
    groups.sort(key=lambda g: -g.samples)
    pooled: dict[tuple[int, int], list[float]] = defaultdict(list)
    for pairs in ratios.values():
        for key, values in pairs.items():
            pooled[key] += values
    overall = _group_stats("все группы", pooled, latest_year)
    return HistoryIndexation(overall=overall, groups=groups, computed_at=(today or date.today()).isoformat())


def years_between(start: date, end: date) -> float:
    """Доля лет между датами по дням; в прошлое — ноль (цены задним числом не индексируем)."""
    return max(0.0, (end - start).days / 365.25)


def indexation_factor(rate_percent: float, start: date, end: date) -> float:
    return (1 + rate_percent / 100) ** years_between(start, end)


def rate_for(section: str, rates: dict[str, float]) -> float | None:
    """Ставка раздела; если своей нет — общая (ключ «»); если и её нет — None."""
    if section in rates:
        return rates[section]
    key = section.strip().lower()
    for name, rate in rates.items():
        if name.strip().lower() == key:
            return rate
    return rates.get("")


class IndexationStore:
    """Ставки индексации по разделам, выбранные оператором: ``DATA_DIR/indexation.json``.
    Один справочник на сервис — ставки общие для всех объектов, дата поставки у каждого своя."""

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir or os.environ.get("DATA_DIR") or DEFAULT_DATA_DIR)
        self.path = self.data_dir / "indexation.json"
        self._rates: dict[str, IndexationRate] = {}
        self._lock = threading.Lock()

    def load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        with self._lock:
            self._rates = {r["section"]: IndexationRate.model_validate(r) for r in raw.get("rates", [])}

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            payload = {"rates": [r.model_dump() for r in self._rates.values()]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def list(self) -> list[IndexationRate]:
        with self._lock:
            return sorted((r.model_copy() for r in self._rates.values()), key=lambda r: (r.section == "", r.section.lower()))

    def set_rates(self, rates: list[IndexationRate]) -> list[IndexationRate]:
        """Заменить справочник целиком (что прислал интерфейс, то и хранится)."""
        today = datetime.now(MOSCOW).date().isoformat()
        with self._lock:
            self._rates = {}
            for rate in rates:
                section = " ".join(rate.section.split())
                self._rates[section] = rate.model_copy(update={"section": section, "updated_at": rate.updated_at or today})
        self.save()
        return self.list()

    def as_dict(self) -> dict[str, float]:
        with self._lock:
            return {section: r.rate for section, r in self._rates.items()}
