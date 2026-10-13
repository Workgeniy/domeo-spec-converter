"""Только извлечение текста выбранных страниц плана, без OCR и сопоставления товаров."""
from __future__ import annotations

import pymupdf

from .pdf_reader import read_page
from .table import detect_layout


def drawing_text(content: bytes, pages: list[int]) -> dict:
    result = []
    with pymupdf.open(stream=content, filetype="pdf") as document:
        if not pages or len(pages) > 20 or any(p < 1 or p > len(document) for p in pages):
            raise ValueError(f"Выберите от 1 до 20 страниц плана в диапазоне 1–{len(document)}.")
        for number in dict.fromkeys(pages):
            page = document[number - 1]
            data = read_page(page, number)
            reason = ""
            if not data.words or (not data.has_text_layer and data.image_coverage > .5):
                reason = "Нет текстового слоя. Сканы в этой версии не сверяются."
            elif detect_layout(data) is not None:
                reason = "Таблица спецификации пропущена: выберите страницу с планом."
            lines = []
            if not reason:
                groups = {}
                allowed_blocks = {word.block for word in data.words}
                for x0, y0, x1, y1, text, block, line, word in page.get_text("words"):
                    if block not in allowed_blocks:
                        continue
                    groups.setdefault((block, line), []).append((word, text, x0, y0))
                for words in groups.values():
                    words.sort()
                    text = " ".join(w[1] for w in words)
                    if len(text) <= 100:
                        point = pymupdf.Point(words[0][2], words[0][3]) * page.rotation_matrix
                        lines.append({"text": text, "x": round(point.x, 1), "y": round(point.y, 1)})
            result.append({"number": number, "skipped_reason": reason, "lines": lines})
    return {"pages": result}
