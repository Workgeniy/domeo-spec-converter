"""Чтение страниц PDF: слова с координатами, линии таблицы, признак скана.

Координаты PyMuPDF отдаёт в системе неповёрнутой страницы, а листы спецификаций
часто хранятся повёрнутыми на 90°. Всё приводится к отображаемой системе через
``page.rotation_matrix``, чтобы дальше таблица всегда была «стоячей».
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

import pymupdf

from .geometry import PageData, Rules, Word

# Блоки текста, которые не относятся к таблице: наложенные штампы и служебные
# подписи систем документооборота. Такие блоки целиком выбрасываются.
IGNORED_BLOCK_PATTERNS = [
    re.compile(r"в производство работ", re.I),
    re.compile(r"передан через диадок", re.I),
    re.compile(r"^\s*ФИО\s*$", re.I),
    re.compile(r"«___»"),
    re.compile(r"^\s*Страница \d+ из \d+\s*$", re.I),
    re.compile(r"^\s*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"),  # идентификатор документа Диадок
]
# Блоки, которые выбрасываются только рядом со штампом: организация, ФИО, дата.
STAMP_NEIGHBOUR_PATTERNS = [
    re.compile(r"(?<![а-яА-Яa-zA-Z])([ОO]{3}|[АA][ОO]|[ПP][АA][ОO]|[ЗZ][АA][ОO]|[ИI][ПP])(?![а-яА-Яa-zA-Z])"),
    re.compile(r"г\.?\s*Москва|\bул\b|ДОМ\s+\d|СТР\s+\d|ПОМ/КОМН", re.I),
    re.compile(r"^[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+$"),  # Фамилия Имя Отчество
    re.compile(r"^\d{1,2}\s+[А-ЯЁа-яё]+\s+\d{2,4}$"),  # «27 Июнь 23»
    re.compile(r"^_{5,}$"),
]

# Меньше этого числа слов на странице — считаем, что текстового слоя нет.
MIN_WORDS_FOR_TEXT_LAYER = 15


def open_document(source: str | Path | bytes) -> pymupdf.Document:
    if isinstance(source, (bytes, bytearray)):
        return pymupdf.open(stream=bytes(source), filetype="pdf")
    return pymupdf.open(str(source))


def read_pages(doc: pymupdf.Document) -> Iterator[PageData]:
    for index, page in enumerate(doc):
        yield read_page(page, index + 1)


def read_page(page: pymupdf.Page, number: int) -> PageData:
    matrix = page.rotation_matrix
    rect = page.rect

    ignored_blocks = _find_ignored_blocks(page)
    words: list[Word] = []
    for x0, y0, x1, y1, text, block_no, *_ in page.get_text("words"):
        if block_no in ignored_blocks:
            continue
        r = pymupdf.Rect(x0, y0, x1, y1) * matrix
        r.normalize()
        # Мягкий перенос (U+00AD) в текстовом слое встречается вместо обычного дефиса.
        text = text.replace("\xad", "-").strip()
        if text:
            words.append(Word(r.x0, r.y0, r.x1, r.y1, text, block_no))

    return PageData(
        number=number,
        width=rect.width,
        height=rect.height,
        words=words,
        has_text_layer=len(words) >= MIN_WORDS_FOR_TEXT_LAYER,
        image_coverage=_image_coverage(page),
        ignored_blocks=[f"стр. {number}: блок {b}" for b in sorted(ignored_blocks)],
        rules_loader=lambda: read_rules(page),
    )


def read_rules(page: pymupdf.Page) -> Rules:
    matrix = page.rotation_matrix
    rules = Rules()
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "l":
                p1, p2 = item[1] * matrix, item[2] * matrix
                rules.add_segment(p1.x, p1.y, p2.x, p2.y)
            elif item[0] == "re":
                r = item[1] * matrix
                r.normalize()
                # Тонкий прямоугольник — это линия; широкий — рамка ячейки, берём его стороны.
                if r.width < 1.5 or r.height < 1.5:
                    rules.add_segment(r.x0, r.y0, r.x1, r.y1)
                else:
                    rules.add_segment(r.x0, r.y0, r.x1, r.y0)
                    rules.add_segment(r.x0, r.y1, r.x1, r.y1)
                    rules.add_segment(r.x0, r.y0, r.x0, r.y1)
                    rules.add_segment(r.x1, r.y0, r.x1, r.y1)
    return rules


# На сколько пунктов вокруг найденного штампа отбрасывать соседние блоки
# (подпись, дата, организация набраны отдельными блоками рядом с ним).
STAMP_NEIGHBOURHOOD = 30


def _find_ignored_blocks(page: pymupdf.Page) -> set[int]:
    blocks = [b for b in page.get_text("blocks") if b[6] == 0]
    # Окрестность штампа: чуть шире его по горизонтали и на STAMP_NEIGHBOURHOOD выше/ниже.
    stamp_rects = [
        pymupdf.Rect(b[:4]) + (-20, -STAMP_NEIGHBOURHOOD, 20, STAMP_NEIGHBOURHOOD)
        for b in blocks
        if any(p.search(b[4]) for p in IGNORED_BLOCK_PATTERNS)
    ]
    ignored: set[int] = set()
    for b in blocks:
        rect = pymupdf.Rect(b[:4])
        if any(p.search(b[4]) for p in IGNORED_BLOCK_PATTERNS):
            ignored.add(b[5])
        elif any(rect in s for s in stamp_rects) and any(
            p.search(re.sub(r"\s+", " ", b[4]).strip()) for p in STAMP_NEIGHBOUR_PATTERNS
        ):
            ignored.add(b[5])
    return ignored


def _image_coverage(page: pymupdf.Page) -> float:
    area = page.rect.width * page.rect.height
    if area <= 0:
        return 0.0
    covered = 0.0
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & page.rect
        covered += max(r.width, 0) * max(r.height, 0)
    return min(covered / area, 1.0)


def render_page(page: pymupdf.Page, dpi: int = 300) -> pymupdf.Pixmap:
    """Растр страницы в отображаемой ориентации (для OCR)."""
    return page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
