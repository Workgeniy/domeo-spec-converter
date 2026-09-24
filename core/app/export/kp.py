"""Расчёт цен коммерческого предложения.

Единственное место, где базовая цена строки превращается в цену КП. Те же правила
продублированы на фронте (web/src/kp.ts) для живых итогов — менять синхронно.

    цена в КП   = база × (1 + наценка)                    → графа J (товар, с НДС)
    СМР за ед.  = цена в КП × СМР%                        → графа K
    M           = цена в КП + СМР                         → графа M (вкл. СМР, с НДС)
    без НДС     = цена в КП / (1 + ставка)                → графа H (формулой в Excel)
    доставка    = стоимость товара по КП × доставка%      → отдельная строка итогов
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..models import KpSettings, SummaryItem


@dataclass(frozen=True)
class RowPrice:
    sale: float  # цена товара за единицу в КП, с НДС
    installation: float  # СМР за единицу, с НДС
    unit_total: float  # цена за единицу вкл. СМР (графа M)


def round_half_up(value: float, digits: int) -> float:
    """Округление «половина вверх», как Math.round на фронте. Встроенный round() у Python
    банковский (80.5 → 80), и предпросмотр в интерфейсе расходился бы с Excel на копейку."""
    k = 10**digits
    return math.floor(value * k + 0.5) / k


def price_row(base: float, settings: KpSettings) -> RowPrice:
    digits = 0 if settings.round_to_ruble else 2
    sale = round_half_up(base * (1 + settings.markup_percent / 100), digits)
    installation = round_half_up(sale * settings.installation_percent / 100, digits)
    return RowPrice(sale, installation, round_half_up(sale + installation, digits))


@dataclass
class KpTotals:
    positions: int = 0
    priced: int = 0
    goods_with_vat: float = 0.0
    goods_without_vat: float = 0.0
    vat: float = 0.0
    installation: float = 0.0
    delivery: float = 0.0

    @property
    def total(self) -> float:
        return round(self.goods_with_vat + self.installation + self.delivery, 2)


def totals(summary: list[SummaryItem], settings: KpSettings) -> KpTotals:
    t = KpTotals(positions=len(summary))
    for item in summary:
        if item.price is None or item.qty is None:
            continue
        p = price_row(item.price, settings)
        t.priced += 1
        t.goods_with_vat += p.sale * item.qty
        t.installation += p.installation * item.qty
    t.goods_without_vat = round_half_up(t.goods_with_vat / (1 + settings.vat_rate), 2)
    t.vat = round_half_up(t.goods_with_vat - t.goods_without_vat, 2)
    t.delivery = round_half_up(t.goods_with_vat * settings.delivery_percent / 100, 2)
    t.goods_with_vat = round_half_up(t.goods_with_vat, 2)
    t.installation = round_half_up(t.installation, 2)
    return t


def parse_date(value: str) -> date | None:
    value = value.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def format_date(value: str, fallback: str = "«___» __________ 20__ г.") -> str:
    d = parse_date(value)
    return d.strftime("%d.%m.%Y") if d else (value or fallback)


def valid_until(settings: KpSettings) -> str:
    d = parse_date(settings.date)
    if d is None or settings.valid_days <= 0:
        return ""
    return (d + timedelta(days=settings.valid_days)).strftime("%d.%m.%Y")
