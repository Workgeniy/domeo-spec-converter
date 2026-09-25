"""Прайс закупки: по каждой позиции истории — все покупки и эталонные цены.

Эталоны считаются по покупкам без явных артефактов учёта: в выгрузке встречаются цены
1 ₽ за фотоаппарат и 100 ₽ за МФУ (частичные оплаты, ошибочные количества). Покупка
считается выбросом, если её цена дальше чем в OUTLIER_RATIO раз от медианы по позиции;
такие покупки остаются в списке с пометкой, но в минимум/максимум не входят.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from .history import PurchaseRow, normalize_name, read_history

OUTLIER_RATIO = 5.0


class Purchase(BaseModel):
    purchased_at: date | None = None
    unit_price: float
    qty: float
    partner_item: str = ""  # что реально купили (номенклатура поставщика) или «комплект: N компонентов»
    order: str = ""
    outlier: bool = False  # выпадает из ряда цен по позиции — в эталоны не входит


class PriceEntry(BaseModel):
    """Позиция прайса: имя из истории и всё, что о ней известно."""

    key: str  # нормализованное наименование
    name: str  # как чаще всего написано в истории
    group: str = ""
    descriptions: list[str] = Field(default_factory=list)  # описания из спецификаций, где встречалась
    purchases: list[Purchase] = Field(default_factory=list)
    price_min: float | None = None  # эталоны: по покупкам без выбросов
    price_max: float | None = None
    price_median: float | None = None
    price_last: float | None = None
    last_date: date | None = None

    @property
    def count(self) -> int:
        return len(self.purchases)


class PriceList(BaseModel):
    source: str = ""
    built_at: date | None = None
    rows_total: int = 0
    entries: list[PriceEntry] = Field(default_factory=list)

    def by_key(self) -> dict[str, PriceEntry]:
        return {e.key: e for e in self.entries}

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=None), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> PriceList:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


def build_price_list(rows: list[PurchaseRow], source: str = "") -> PriceList:
    groups: dict[str, list[PurchaseRow]] = defaultdict(list)
    for row in rows:
        groups[normalize_name(row.name)].append(row)

    entries: list[PriceEntry] = []
    for key, group_rows in groups.items():
        purchases = _purchases(group_rows)
        if not purchases:
            continue
        _mark_outliers(purchases)
        clean = [p for p in purchases if not p.outlier]
        prices = [p.unit_price for p in clean]
        dated = sorted((p for p in clean if p.purchased_at), key=lambda p: p.purchased_at)  # type: ignore[arg-type]
        entries.append(
            PriceEntry(
                key=key,
                name=_most_common(r.name for r in group_rows),
                group=_most_common(r.group for r in group_rows if r.group),
                descriptions=_unique(r.description for r in group_rows if r.description)[:5],
                purchases=sorted(purchases, key=lambda p: (p.purchased_at or date.min), reverse=True),
                price_min=min(prices) if prices else None,
                price_max=max(prices) if prices else None,
                price_median=statistics.median(prices) if prices else None,
                price_last=dated[-1].unit_price if dated else (prices[-1] if prices else None),
                last_date=dated[-1].purchased_at if dated else None,
            )
        )
    entries.sort(key=lambda e: e.key)
    return PriceList(source=source, built_at=date.today(), rows_total=len(rows), entries=entries)


def build_from_file(path: str | Path) -> PriceList:
    return build_price_list(read_history(path), source=Path(path).name)


def _purchases(rows: list[PurchaseRow]) -> list[Purchase]:
    """Обычные строки — по одной покупке; компоненты одной сборки — один комплект."""
    purchases: list[Purchase] = []
    assemblies: dict[str, list[PurchaseRow]] = defaultdict(list)
    for row in rows:
        if row.assembly:
            assemblies[row.assembly].append(row)
        elif row.unit_price is not None:
            purchases.append(
                Purchase(purchased_at=row.order_date, unit_price=round(row.unit_price, 2), qty=row.qty or 0, partner_item=row.partner_item, order=row.order)
            )
    for assembly, parts in assemblies.items():
        total = sum(p.total for p in parts if p.total is not None)
        assemble_qty = next((p.assemble_qty for p in parts if p.assemble_qty), None)
        if not total or not assemble_qty:
            continue
        dates = [p.order_date for p in parts if p.order_date]
        purchases.append(
            Purchase(
                purchased_at=min(dates) if dates else None,
                unit_price=round(total / assemble_qty, 2),
                qty=assemble_qty,
                partner_item=f"комплект: {len(parts)} компонентов",
                order=assembly,
            )
        )
    return purchases


def _mark_outliers(purchases: list[Purchase]) -> None:
    if len(purchases) < 3:
        return
    median = statistics.median(p.unit_price for p in purchases)
    if median <= 0:
        return
    for p in purchases:
        ratio = p.unit_price / median
        p.outlier = ratio > OUTLIER_RATIO or ratio < 1 / OUTLIER_RATIO


def _most_common(values) -> str:
    counts: dict[str, int] = defaultdict(int)
    for v in values:
        counts[v] += 1
    return max(counts, key=counts.get) if counts else ""  # type: ignore[arg-type]


def _unique(values) -> list[str]:
    seen: list[str] = []
    for v in values:
        if v not in seen:
            seen.append(v)
    return seen


def summary(price_list: PriceList) -> dict:
    """Короткая сводка для отчёта и интерфейса."""
    entries = price_list.entries
    period_from = min((e.purchases[-1].purchased_at for e in entries if e.purchases and e.purchases[-1].purchased_at), default=None)
    period_to = max((e.last_date for e in entries if e.last_date), default=None)
    return {
        "source": price_list.source,
        "built_at": price_list.built_at.isoformat() if price_list.built_at else "",
        "rows_total": price_list.rows_total,
        "entries": len(entries),
        "with_two_or_more": sum(1 for e in entries if e.count >= 2),
        "purchases": sum(e.count for e in entries),
        "outliers": sum(1 for e in entries for p in e.purchases if p.outlier),
        "period_from": period_from.isoformat() if period_from else None,
        "period_to": period_to.isoformat() if period_to else None,
    }


def dump_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
