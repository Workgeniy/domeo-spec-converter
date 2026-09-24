"""Примитивы геометрии страницы: слова с координатами и линии разметки таблицы.

Все координаты — в «отображаемой» системе страницы (после поворота), в пунктах PDF.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block: int = 0  # номер текстового блока в исходнике (для фильтрации штампов)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class Rules:
    """Линии таблицы: координата -> суммарная длина отрезков на этой координате.

    Границы ячеек часто рисуются по отдельности для каждой ячейки, поэтому одна
    граница столбца складывается из десятков коротких отрезков. Суммарная длина
    позволяет отличить настоящую границу от случайного штриха.
    """

    vertical: dict[int, float] = field(default_factory=lambda: defaultdict(float))
    horizontal: dict[int, float] = field(default_factory=lambda: defaultdict(float))

    def add_segment(self, x0: float, y0: float, x1: float, y1: float) -> None:
        if abs(x0 - x1) < 1.5 and abs(y0 - y1) >= 4:
            self.vertical[round((x0 + x1) / 2)] += abs(y1 - y0)
        elif abs(y0 - y1) < 1.5 and abs(x0 - x1) >= 4:
            self.horizontal[round((y0 + y1) / 2)] += abs(x1 - x0)

    def columns(self, min_length: float) -> list[float]:
        return _merge_close(_filter(self.vertical, min_length))

    def rows(self, min_length: float) -> list[float]:
        return _merge_close(_filter(self.horizontal, min_length))


@dataclass
class PageData:
    number: int  # с единицы
    width: float
    height: float
    words: list[Word]
    has_text_layer: bool
    image_coverage: float  # доля площади страницы, закрытая картинками (0..1)
    source: str = "text"  # text | ocr | skipped
    ignored_blocks: list[str] = field(default_factory=list)
    # Линии извлекаются лениво: на чертежах их тысячи, а нужны они только на
    # страницах со спецификацией.
    rules_loader: Callable[[], Rules] | None = None
    _rules: Rules | None = None

    @property
    def rules(self) -> Rules:
        if self._rules is None:
            self._rules = self.rules_loader() if self.rules_loader else Rules()
        return self._rules


def _filter(values: dict[int, float], min_length: float) -> list[float]:
    return sorted(coord for coord, length in values.items() if length >= min_length)


def _merge_close(coords: list[float], tolerance: float = 2.5) -> list[float]:
    """Соседние координаты (границы шириной в пару пунктов) сливаются в одну."""
    merged: list[float] = []
    for c in coords:
        if merged and c - merged[-1] <= tolerance:
            merged[-1] = (merged[-1] + c) / 2
        else:
            merged.append(c)
    return merged


def group_into_lines(words: list[Word], tolerance: float = 3.0) -> list[list[Word]]:
    """Группирует слова в строки текста по вертикальному центру, внутри строки — слева направо."""
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.cy, w.x0)):
        if lines and abs(lines[-1][-1].cy - w.cy) <= tolerance:
            lines[-1].append(w)
        else:
            lines.append([w])
    for line in lines:
        line.sort(key=lambda w: w.x0)
    return lines
