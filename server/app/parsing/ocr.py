"""OCR для сканированных страниц.

Скан проходит тот же конвейер, что и страница с текстовым слоем: из растра
получаем слова с координатами и линии таблицы, дальше работает общий разбор.

Провайдер OCR подключается через ``OcrProvider``; по умолчанию используется
Tesseract (нужен установленный бинарник и русский языковой пакет). Если он не
найден, страница помечается как пропущенная с понятным предупреждением.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pymupdf

from .geometry import PageData, Rules, Word

OCR_DPI = 300
POINTS_PER_INCH = 72.0


class OcrProvider(Protocol):
    name: str

    def recognize(self, pixmap: pymupdf.Pixmap) -> list[Word]:
        """Слова в пикселях растра (x0, y0, x1, y1 относительно pixmap)."""


@dataclass
class TesseractProvider:
    lang: str = "rus+eng"
    name: str = "tesseract"

    @staticmethod
    def available() -> bool:
        return shutil.which("tesseract") is not None

    def recognize(self, pixmap: pymupdf.Pixmap) -> list[Word]:
        import pytesseract
        from PIL import Image

        image = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
        data = pytesseract.image_to_data(
            image, lang=self.lang, config="--psm 6", output_type=pytesseract.Output.DICT
        )
        words: list[Word] = []
        for i, text in enumerate(data["text"]):
            text = (text or "").strip()
            if not text or int(data["conf"][i]) < 0:
                continue
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            words.append(Word(x, y, x + w, y + h, text, block=int(data["block_num"][i])))
        return words


def default_provider() -> OcrProvider | None:
    if TesseractProvider.available():
        return TesseractProvider()
    return None


def ocr_page(page: pymupdf.Page, number: int, provider: OcrProvider, dpi: int = OCR_DPI) -> PageData:
    pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    scale = POINTS_PER_INCH / dpi
    words = [
        Word(w.x0 * scale, w.y0 * scale, w.x1 * scale, w.y1 * scale, w.text, w.block)
        for w in provider.recognize(pixmap)
    ]
    rules = detect_rules(pixmap, scale)
    return PageData(
        number=number,
        width=page.rect.width,
        height=page.rect.height,
        words=words,
        has_text_layer=False,
        image_coverage=1.0,
        source="ocr",
        rules_loader=lambda: rules,
    )


def detect_rules(pixmap: pymupdf.Pixmap, scale: float, min_run_px: int = 40) -> Rules:
    """Находит линии таблицы на растре по длинным прогонам тёмных пикселей.

    Достаточно грубого метода: считаем в каждой строке/столбце пикселей самый
    длинный непрерывный тёмный прогон и берём его как отрезок линии.
    """
    img = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width)
    dark = img < 128
    rules = Rules()
    for y, run in enumerate(_longest_runs(dark)):
        if run >= min_run_px:
            rules.add_segment(0, y * scale, run * scale, y * scale)
    for x, run in enumerate(_longest_runs(dark.T)):
        if run >= min_run_px:
            rules.add_segment(x * scale, 0, x * scale, run * scale)
    return rules


def _longest_runs(mask: np.ndarray) -> np.ndarray:
    """Для каждой строки булевой матрицы — длина самого длинного прогона True."""
    padded = np.zeros((mask.shape[0], mask.shape[1] + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    diff = np.diff(padded, axis=1)
    result = np.zeros(mask.shape[0], dtype=np.int64)
    for i in range(mask.shape[0]):
        starts = np.flatnonzero(diff[i] == 1)
        ends = np.flatnonzero(diff[i] == -1)
        if len(starts):
            result[i] = (ends - starts).max()
    return result
