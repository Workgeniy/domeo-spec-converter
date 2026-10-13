"""Расчёт цен коммерческого предложения.

Единственное место, где базовая цена строки превращается в цену КП. Те же правила
продублированы на фронте (web/src/kp.ts) для живых итогов — менять синхронно.

    цена в КП   = база × (1 + наценка) × (1 + доставка)   → графа «Цена за ед. товара, с НДС»
    СМР за ед.  = цена в КП × СМР%  (только лист «1»)     → графа «Цена за ед. СМР, с НДС»
    M           = цена в КП + СМР                         → «Цена за ед. товара (вкл. СМР), с НДС»
    без НДС     = цена в КП / (1 + ставка)                → формулой в Excel

Доставка входит в цену товара — в образце заказчика это графа-подсказка «дост» у каждой
строки, отдельной строки доставки в приложениях нет.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime

from ..models import KpSettings, SummaryItem


@dataclass(frozen=True)
class RowPrice:
    sale: float  # цена товара за единицу в КП, с НДС
    installation: float  # СМР за единицу, с НДС (0 для инвентаря без монтажа)
    unit_total: float  # цена за единицу вкл. СМР (графа M листа «1»)


def round_half_up(value: float, digits: int) -> float:
    """Округление «половина вверх», как Math.round на фронте. Встроенный round() у Python
    банковский (80.5 → 80), и предпросмотр в интерфейсе расходился бы с Excel на копейку."""
    k = 10**digits
    return math.floor(value * k + 0.5) / k


def effective_markup(settings: KpSettings) -> float:
    """Эквивалент наценки для служебной графы «пр», совместимой со старыми шаблонами."""
    return settings.markup_percent if settings.margin_percent is None else 100 * settings.margin_percent / (100 - settings.margin_percent)


def price_row(base: float, settings: KpSettings, with_installation: bool = True) -> RowPrice:
    digits = 0 if settings.round_to_ruble else 2
    multiplier = 1 + settings.markup_percent / 100 if settings.margin_percent is None else 1 / (1 - settings.margin_percent / 100)
    sale = round_half_up(base * multiplier * (1 + settings.delivery_percent / 100), digits)
    installation = round_half_up(sale * settings.installation_percent / 100, digits) if with_installation else 0.0
    return RowPrice(sale, installation, round_half_up(sale + installation, digits))


@dataclass
class KpTotals:
    positions: int = 0
    mounted: int = 0  # позиций на листе «1» (с монтажом)
    inventory: int = 0  # позиций на листе «2»
    priced: int = 0
    goods_with_vat: float = 0.0
    goods_without_vat: float = 0.0
    vat: float = 0.0
    installation: float = 0.0

    @property
    def total(self) -> float:
        return round_half_up(self.goods_with_vat + self.installation, 2)


def totals(summary: list[SummaryItem], settings: KpSettings) -> KpTotals:
    t = KpTotals(positions=len(summary))
    for item in summary:
        if item.installation:
            t.mounted += 1
        else:
            t.inventory += 1
        if item.price is None or item.qty is None:
            continue
        p = price_row(item.price, settings, item.installation)
        t.priced += 1
        t.goods_with_vat += p.sale * item.qty
        t.installation += p.installation * item.qty
    t.goods_without_vat = round_half_up(t.goods_with_vat / (1 + settings.vat_rate), 2)
    t.vat = round_half_up(t.goods_with_vat - t.goods_without_vat, 2)
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
