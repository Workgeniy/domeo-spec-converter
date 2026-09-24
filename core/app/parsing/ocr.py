"""OCR для сканированных страниц.

Скан проходит тот же конвейер, что и страница с текстовым слоем: из растра
получаем слова с координатами и линии таблицы, дальше работает общий разбор.

Tesseract по целой странице теряет строки таблицы (шапку с короткими ячейками он часто
выбрасывает как «не текст»), поэтому, когда на растре найдена сетка линий, распознаётся
каждая ячейка отдельно: вырезки ячеек складываются столбиком в один холст, холст
распознаётся за один вызов, слова возвращаются на свои места по таблице смещений.
Без сетки — распознаётся страница целиком.

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
from PIL import Image

from .geometry import PageData, Rules, Word

OCR_DPI = 300
POINTS_PER_INCH = 72.0
# Промежуток между вырезками ячеек на общем холсте — чтобы строки соседних ячеек не слиплись.
CELL_GAP_PX = 30
# Меньше стольких тёмных пикселей — ячейка пустая, распознавать нечего.
BLANK_CELL_DARK_PX = 25
# Отступ от линии сетки внутрь ячейки и полоса у края, в которой остатки линий затираются:
# обрывок линии в вырезке Tesseract принимает за символ («—», «_», «ВИ»).
CELL_INSET_PX = 4
CELL_EDGE_PX = 10


@dataclass(frozen=True)
class Region:
    """Откуда на странице взята вырезка и где она лежит на холсте (всё в пикселях растра)."""

    x0: int
    y0: int
    x1: int
    y1: int
    canvas_y: int


class OcrProvider(Protocol):
    name: str

    def recognize(self, image: Image.Image, regions: list[Region]) -> list[Word]:
        """Слова в пикселях переданного изображения.

        ``regions`` описывает, из каких мест страницы собран холст; настоящему OCR они не
        нужны, подставным провайдерам в тестах — нужны."""


@dataclass
class TesseractProvider:
    lang: str = "rus+eng"
    name: str = "tesseract"

    @staticmethod
    def available() -> bool:
        return shutil.which("tesseract") is not None

    def recognize(self, image: Image.Image, regions: list[Region]) -> list[Word]:
        return self._run(image, "--psm 6")

    def recognize_cell(self, image: Image.Image, digits: bool = False) -> list[Word]:
        """Повторное чтение одной ячейки как одной строки; ``digits`` — только цифры."""
        config = "--psm 7"
        if digits:
            config += " -c tessedit_char_whitelist=0123456789.,"
        return self._run(image, config)

    def _run(self, image: Image.Image, config: str) -> list[Word]:
        import pytesseract

        data = pytesseract.image_to_data(image, lang=self.lang, config=config, output_type=pytesseract.Output.DICT)
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
    image = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
    scale = POINTS_PER_INCH / dpi
    rules = detect_rules(pixmap, scale)

    cells = grid_cells(rules, image, page.rect.width, page.rect.height, scale)
    if cells:
        px_words = _recognize_cells(image, cells, provider)
    else:
        px_words = provider.recognize(image, [Region(0, 0, image.width, image.height, 0)])

    words = [Word(w.x0 * scale, w.y0 * scale, w.x1 * scale, w.y1 * scale, w.text, w.block) for w in px_words]
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


def grid_cells(rules: Rules, image: Image.Image, page_w: float, page_h: float, scale: float) -> list[tuple[int, int, int, int]]:
    """Ячейки сетки (в пикселях растра) по найденным на растре линиям; пустые пропускаются."""
    xs = [round(x / scale) for x in rules.columns(page_h * 0.25)]
    ys = [round(y / scale) for y in rules.rows(page_w * 0.35)]
    if len(xs) < 3 or len(ys) < 3:
        return []
    cells: list[tuple[int, int, int, int]] = []
    for y0, y1 in zip(ys, ys[1:]):
        for x0, x1 in zip(xs, xs[1:]):
            box = (x0 + CELL_INSET_PX, y0 + CELL_INSET_PX, x1 - CELL_INSET_PX, y1 - CELL_INSET_PX)
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                continue
            if np.count_nonzero(np.asarray(crop_cell(image, box)) < 128) < BLANK_CELL_DARK_PX:
                continue
            cells.append(box)
    return cells


def crop_cell(image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    """Вырезка ячейки с затёртыми остатками линий сетки у краёв."""
    arr = np.array(image.crop(box))
    h, w = arr.shape
    edge = min(CELL_EDGE_PX, h // 4, w // 4)
    for band in (arr[:edge], arr[h - edge :]):
        for row in band:
            if np.count_nonzero(row < 128) > 0.5 * w:
                row[:] = 255
    for band in (arr[:, :edge], arr[:, w - edge :]):
        for col in band.T:
            if np.count_nonzero(col < 128) > 0.5 * h:
                col[:] = 255
    return Image.fromarray(arr)


def _recognize_cells(image: Image.Image, cells: list[tuple[int, int, int, int]], provider: OcrProvider) -> list[Word]:
    """Один вызов OCR на страницу: вырезки ячеек столбиком на общем холсте, слова — обратно по смещениям."""
    width = max(x1 - x0 for x0, _, x1, _ in cells)
    height = sum(y1 - y0 + CELL_GAP_PX for _, y0, _, y1 in cells)
    canvas = Image.new("L", (width, height), 255)
    regions: list[Region] = []
    y = 0
    for x0, y0, x1, y1 in cells:
        canvas.paste(crop_cell(image, (x0, y0, x1, y1)), (0, y))
        regions.append(Region(x0, y0, x1, y1, y))
        y += (y1 - y0) + CELL_GAP_PX

    words: list[Word] = []
    found: dict[Region, list[Word]] = {r: [] for r in regions}
    for w in provider.recognize(canvas, regions):
        cy = (w.y0 + w.y1) / 2
        region = next((r for r in regions if r.canvas_y <= cy < r.canvas_y + (r.y1 - r.y0)), None)
        if region is None:
            continue
        dy = region.y0 - region.canvas_y
        found[region].append(Word(w.x0 + region.x0, w.y0 + dy, w.x1 + region.x0, w.y1 + dy, w.text, w.block))

    # Одиночные символы (количество «1», «2») общий проход читает плохо: «1» → «И», «2» → пусто.
    # Такие ячейки перечитываются по одной как строка, при неудаче — в режиме «только цифры».
    retry = getattr(provider, "recognize_cell", None)
    for region, region_words in found.items():
        if retry is not None and _looks_weak(region_words):
            region_words[:] = _retry_cell(image, region, retry) or region_words
        words.extend(region_words)
    return words


def _looks_weak(words: list[Word]) -> bool:
    return not words or (len(words) == 1 and len(words[0].text) == 1 and not words[0].text.isdigit())


def _retry_cell(image: Image.Image, region: Region, retry) -> list[Word]:
    pad, zoom = 12, 2
    crop = crop_cell(image, (region.x0, region.y0, region.x1, region.y1))
    big = Image.new("L", (crop.width * zoom + 2 * pad, crop.height * zoom + 2 * pad), 255)
    big.paste(crop.resize((crop.width * zoom, crop.height * zoom), Image.LANCZOS), (pad, pad))
    result = retry(big)
    if _looks_weak(result):
        # Строкой тоже не прочиталось (или снова одна буква вместо цифры) — пробуем как число.
        result = retry(big, True) or result
    return [
        Word(
            region.x0 + (w.x0 - pad) / zoom,
            region.y0 + (w.y0 - pad) / zoom,
            region.x0 + (w.x1 - pad) / zoom,
            region.y0 + (w.y1 - pad) / zoom,
            w.text,
            w.block,
        )
        for w in result
    ]


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
