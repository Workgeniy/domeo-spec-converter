from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

SAMPLES = Path(__file__).parent / "samples"

# Встроенные шрифты PDF не содержат кириллицы, поэтому для синтетических
# документов берётся системный TTF.
CYRILLIC_FONTS = [
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
]


def cyrillic_font() -> str:
    for path in CYRILLIC_FONTS:
        if path.exists():
            return str(path)
    pytest.skip("не найден системный шрифт с кириллицей для синтетического PDF")


def sample(name: str) -> Path:
    path = SAMPLES / name
    if not path.exists():
        pytest.skip(f"нет файла-образца {name} (папка tests/samples не в git)")
    return path


@pytest.fixture
def synthetic_spec_pdf(tmp_path: Path) -> Path:
    """Маленькая спецификация, нарисованная PyMuPDF: шапка, линии, три строки и штамп.

    Нужна, чтобы тесты работали без файлов заказчика.
    """
    font = cyrillic_font()
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)

    def text(x: float, y: float, value: str, size: float = 8) -> None:
        page.insert_text((x, y), value, fontsize=size, fontname="F0", fontfile=font)
    cols = [40, 90, 420, 520, 600, 680, 730, 780, 820]
    headers = ["Поз.", "Наименование и техническая характеристика", "Тип, марка", "Завод изготовитель",
               "Ед. изм.", "Кол-во", "Масса", "Примечание"]
    rows = [
        ("1.01", ["Групповая комната"], "", "", "", "", "", ""),
        ("2.1", ["Стол воспитателя, ЛДСП 16 мм,", "1000х550х750(h)"], "", "Торговая сеть", "шт.", "1", "", ""),
        ("2.10", ["Стул детский регулируемый", "по высоте №1-№3"], "по типу АБВ-1", "Торговая сеть", "шт.", "26", "", "см. АР"),
        ("б/н", ["Ковёр 2х3 м"], "", "", "компл.", "2", "", ""),
    ]
    top, header_h, row_h = 40, 30, 34
    ys = [top, top + header_h] + [top + header_h + row_h * (i + 1) for i in range(len(rows))]
    for y in ys:
        page.draw_line((cols[0], y), (cols[-1], y))
    for x in cols:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for x, title in zip(cols, headers):
        text(x + 3, top + 18, title, 7)
    for i, (pos, name_lines, tm, mf, unit, qty, mass, note) in enumerate(rows):
        y = ys[i + 1]
        text(cols[0] + 3, y + 20, pos)
        for k, line in enumerate(name_lines):
            text(cols[1] + 3, y + 13 + 11 * k, line)
        for x, value in zip(cols[2:], (tm, mf, unit, qty, mass, note)):
            if value:
                text(x + 3, y + 20, value)
    # штамп внизу
    text(600, 560, "Изм. Кол.уч. Лист №док. Подп. Дата", 7)
    text(600, 575, "Лист 1 Листов 1", 7)
    path = tmp_path / "synthetic.pdf"
    doc.save(path)
    return path


@pytest.fixture
def synthetic_scan_pdf(synthetic_spec_pdf: Path, tmp_path: Path) -> Path:
    """Тот же документ, но как картинка без текстового слоя (имитация скана)."""
    src = pymupdf.open(synthetic_spec_pdf)
    pix = src[0].get_pixmap(dpi=200)
    out = pymupdf.open()
    page = out.new_page(width=src[0].rect.width, height=src[0].rect.height)
    page.insert_image(page.rect, pixmap=pix)
    path = tmp_path / "scan.pdf"
    out.save(path)
    return path
