"""Числовые параметры позиции из характеристик: габариты, объём, масса, мощность, диаметр.

Нужны, чтобы «стеллаж 2000×1000×400» не считался той же позицией, что «стеллаж 2500×1000×400»:
параметры сравниваются отдельно от слов названия и либо подтверждают совпадение, либо
отводят предложение в «похожие». Формы записи у проектировщиков и магазинов разные
(2000х1000х400(h), 2,0×1,0×0,4 м, 120х60 см, 460/520/580 — варианты высоты), поэтому
всё приводится к миллиметрам, литрам, килограммам и киловаттам.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import product

NUM = r"\d+(?:[.,]\d+)?"
SEP = r"\s*[xхХ×X*]\s*"
LEN_UNIT = r"(?:мм|mm|см|cm|м|m)"
DIMS_RE = re.compile(
    rf"(?<![\d.,/])({NUM}(?:\s*/\s*{NUM})*)\s*({LEN_UNIT})?{SEP}({NUM}(?:\s*/\s*{NUM})*)\s*({LEN_UNIT})?(?:{SEP}({NUM}(?:\s*/\s*{NUM})*))?\s*({LEN_UNIT})?(?!\d|[.,]\d)",
    re.I,
)
VOLUME_RE = re.compile(rf"(?<![\d.,])({NUM})\s*(?:л|l|литр\w*)(?![а-яa-z])", re.I)
MASS_RE = re.compile(rf"(?<![\d.,])({NUM})\s*(?:кг|kg)(?![а-яa-z])", re.I)
POWER_RE = re.compile(rf"(?<![\d.,])({NUM})\s*(квт|kw|вт|w)(?![а-яa-z])", re.I)
DIAMETER_RE = re.compile(rf"(?:ø|Ø|⌀|\bd\s*=?|диам\w*)\s*({NUM})\s*({LEN_UNIT})?", re.I)
TOLERANCE = 0.05  # 5 % — округления у разных продавцов
MIN_TOLERANCE_MM = 15


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def _to_mm(value: float, unit: str | None, decimal: bool) -> int:
    unit = (unit or "").lower()
    if unit in ("см", "cm"):
        return round(value * 10)
    if unit in ("м", "m") or (not unit and decimal and value < 20):
        return round(value * 1000)  # «2,0 х 1,0 х 0,4» — метры
    return round(value)


def _variants(text: str, unit: str | None) -> list[int]:
    return [_to_mm(_num(part), unit, "," in part or "." in part) for part in re.split(r"\s*/\s*", text.strip())]


@dataclass
class Params:
    dims: list[list[tuple[int, ...]]] = field(default_factory=list)  # группы габаритов; внутри — варианты
    volume_l: list[float] = field(default_factory=list)
    mass_kg: list[float] = field(default_factory=list)
    power_kw: list[float] = field(default_factory=list)
    diameter_mm: list[int] = field(default_factory=list)

    def empty(self) -> bool:
        return not (self.dims or self.volume_l or self.mass_kg or self.power_kw or self.diameter_mm)

    def describe(self) -> str:
        """Для запроса к поисковику и для комментария: «2000x1000x400 700 л»."""
        parts: list[str] = []
        for group in self.dims[:1]:
            parts.append("x".join(str(v) for v in group[0]))
        parts += [f"{_fmt(v)} л" for v in self.volume_l[:1]]
        parts += [f"{_fmt(v)} кг" for v in self.mass_kg[:1]]
        parts += [f"{_fmt(v)} кВт" for v in self.power_kw[:1]]
        parts += [f"Ø{v}" for v in self.diameter_mm[:1]]
        return " ".join(parts)


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}".replace(".", ",")


def extract_params(text: str) -> Params:
    params = Params()
    if not text:
        return params
    for match in DIMS_RE.finditer(text):
        unit = match.group(6) or match.group(4) or match.group(2)  # «120х60 см», «120 см х 60 см»
        axes = [_variants(g, unit) for g in (match.group(1), match.group(3), match.group(5)) if g]
        combos = [tuple(combo) for combo in product(*axes)]
        # Габариты — не меньше 10 мм по каждой оси, иначе это что-то другое (1х2 шт, 3x4 класс).
        combos = [c for c in combos if all(v >= 10 for v in c)]
        if combos:
            params.dims.append(combos)
    params.volume_l = [_num(m.group(1)) for m in VOLUME_RE.finditer(text)]
    params.mass_kg = [_num(m.group(1)) for m in MASS_RE.finditer(text)]
    for m in POWER_RE.finditer(text):
        value = _num(m.group(1))
        params.power_kw.append(value if m.group(2).lower() in ("квт", "kw") else value / 1000)
    params.diameter_mm = [_to_mm(_num(m.group(1)), m.group(2), "," in m.group(1) or "." in m.group(1)) for m in DIAMETER_RE.finditer(text)]
    return params


def _close(a: float, b: float, minimum: float = 0.0) -> bool:
    return abs(a - b) <= max(minimum, TOLERANCE * max(abs(a), abs(b)))


def _dims_match(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    """Порядок осей у продавца и проектировщика разный; при 2 и 3 осях сверяем общие."""
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    rest = list(long)
    for value in short:
        hit = next((i for i, other in enumerate(rest) if _close(value, other, MIN_TOLERANCE_MM)), None)
        if hit is None:
            return False
        rest.pop(hit)
    return True


def compare_params(spec: Params, offer: Params) -> tuple[int, int]:
    """(совпало, противоречит) по типам параметров, которые есть с обеих сторон."""
    matches = conflicts = 0
    if spec.dims and offer.dims:
        ok = any(_dims_match(s, o) for sg in spec.dims for s in sg for og in offer.dims for o in og)
        matches, conflicts = (matches + 1, conflicts) if ok else (matches, conflicts + 1)
    for spec_values, offer_values, minimum in (
        (spec.volume_l, offer.volume_l, 0.5),
        (spec.mass_kg, offer.mass_kg, 1.0),
        (spec.power_kw, offer.power_kw, 0.05),
        (spec.diameter_mm, offer.diameter_mm, MIN_TOLERANCE_MM),
    ):
        if spec_values and offer_values:
            ok = any(_close(s, o, minimum) for s in spec_values for o in offer_values)
            matches, conflicts = (matches + 1, conflicts) if ok else (matches, conflicts + 1)
    return matches, conflicts
