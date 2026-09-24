from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from app.parsing.geometry import Word
from app.parsing.ocr import OCR_DPI, Region, TesseractProvider, detect_rules, grid_cells
from app.parsing.pdf_reader import read_page
from app.parsing.spec_parser import parse_pdf, parse_qty, short_name
from app.parsing.table import detect_layout

from .conftest import sample


def test_synthetic_spec(synthetic_spec_pdf: Path) -> None:
    doc = parse_pdf(synthetic_spec_pdf)
    assert [p.kind for p in doc.pages] == ["spec"]
    assert [i.pos for i in doc.items] == ["2.1", "2.10", "б/н"]
    stol, stul, kover = doc.items
    assert stol.group == "1.01 Групповая комната"
    assert stol.description == "Стол воспитателя, ЛДСП 16 мм, 1000х550х750(h)"
    assert stol.name == "Стол воспитателя"
    assert stul.qty == 26 and stul.unit == "шт."
    assert stul.type_mark == "по типу АБВ-1"
    assert stul.note == "см. АР"
    assert kover.unit == "компл." and kover.qty == 2
    assert not any(i.warnings for i in doc.items)


def test_scan_without_ocr_is_reported(synthetic_scan_pdf: Path) -> None:
    doc = parse_pdf(synthetic_scan_pdf, ocr=None) if not TesseractProvider.available() else None
    if doc is None:
        return  # OCR установлен — этот сценарий проверяет test_scan_with_fake_ocr
    assert doc.pages[0].source == "skipped"
    assert any("OCR" in w for w in doc.pages[0].warnings)
    assert doc.items == []


def test_scan_with_fake_ocr(synthetic_spec_pdf: Path, synthetic_scan_pdf: Path) -> None:
    """Скан проходит общий конвейер: слова от OCR по ячейкам сетки, линии — с растра."""
    text_words = read_page(pymupdf.open(synthetic_spec_pdf)[0], 1).words
    k = OCR_DPI / 72  # пункты страницы → пиксели растра

    class FakeOcr:
        """Вместо распознавания берёт слова текстового слоя, попавшие в каждую вырезку холста."""

        name = "fake"
        calls = 0

        def recognize(self, image: Image.Image, regions: list[Region]) -> list[Word]:
            self.calls += 1
            words: list[Word] = []
            for r in regions:
                for w in text_words:
                    x0, y0, x1, y1 = w.x0 * k, w.y0 * k, w.x1 * k, w.y1 * k
                    if r.x0 <= (x0 + x1) / 2 < r.x1 and r.y0 <= (y0 + y1) / 2 < r.y1:
                        words.append(Word(x0 - r.x0, y0 - r.y0 + r.canvas_y, x1 - r.x0, y1 - r.y0 + r.canvas_y, w.text))
            return words

    fake = FakeOcr()
    doc = parse_pdf(synthetic_scan_pdf, ocr=fake)
    assert fake.calls == 1  # один вызов OCR на страницу, а не по вызову на ячейку
    assert doc.pages[0].source == "ocr"
    assert doc.pages[0].kind == "spec"
    assert [i.pos for i in doc.items] == ["2.1", "2.10", "б/н"]
    assert doc.items[1].qty == 26
    assert doc.items[0].group == "1.01 Групповая комната"


def test_grid_cells_skip_blank_cells(synthetic_scan_pdf: Path) -> None:
    page = pymupdf.open(synthetic_scan_pdf)[0]
    pix = page.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY)
    image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    cells = grid_cells(detect_rules(pix, 72 / OCR_DPI), image, page.rect.width, page.rect.height, 72 / OCR_DPI)
    # 8 столбцов × 5 строк = 40 ячеек; с текстом — 8 в шапке и 18 в строках, плюс пара ячеек,
    # куда заползает текст соседней (шапка «Завод изготовитель» шире своей графы).
    assert 24 <= len(cells) <= 32


@pytest.mark.skipif(not TesseractProvider.available(), reason="Tesseract не установлен")
def test_scan_with_real_tesseract(synthetic_scan_pdf: Path) -> None:
    doc = parse_pdf(synthetic_scan_pdf, ocr=TesseractProvider())
    assert doc.pages[0].kind == "spec" and doc.pages[0].source == "ocr"
    assert [i.pos for i in doc.items] == ["2.1", "2.10", "б/н"]
    # Одиночные цифры («1», «2») общий проход читает плохо — их добирает повторное чтение ячейки.
    assert [i.qty for i in doc.items] == [1, 26, 2]
    assert [i.unit for i in doc.items] == ["шт.", "шт.", "компл."]


def test_detect_rules_on_raster(synthetic_scan_pdf: Path) -> None:
    page = pymupdf.open(synthetic_scan_pdf)[0]
    pix = page.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
    rules = detect_rules(pix, 72 / 150)
    assert len(rules.columns(200)) >= 8
    assert len(rules.rows(400)) >= 5


def test_layout_falls_back_to_anchors_without_rules(synthetic_spec_pdf: Path) -> None:
    data = read_page(pymupdf.open(synthetic_spec_pdf)[0], 1)
    data.rules_loader = None  # как будто линий нет совсем
    layout = detect_layout(data)
    assert layout is not None
    assert layout.row_mode == "anchors"
    assert {c.key for c in layout.columns} >= {"pos", "name", "unit", "qty"}


def test_short_name() -> None:
    assert short_name("Стул офисный на металлическом каркасе, каркас труба") == "Стул офисный на металлическом каркасе"
    assert short_name("Полка навесная. Наличие отверстия для проводов.") == "Полка навесная"
    assert short_name("Стол, ЛДСП") == "Стол, ЛДСП"


def test_parse_qty() -> None:
    assert parse_qty("26") == 26
    assert parse_qty("83,2") == 83.2
    assert parse_qty("2 шт") is None


# ---------- реальные документы (пропускаются, если образцов нет) ----------


def test_weltbau_tx2() -> None:
    doc = parse_pdf(sample("ДОО350-ДОН-ПИР-П-ТХ2.pdf"))
    assert doc.doc_code == "ДОО350-ДОН-ПИР-П-ТХ2"
    assert len([p for p in doc.pages if p.kind == "spec"]) == 7
    assert len(doc.items) == 139
    first = doc.items[0]
    assert first.pos == "7.197" and first.qty == 1 and first.type_mark.startswith("по типу GTStandart")
    assert "Загрузочный цех" in doc.items[1].group
    assert not any(i.warnings for i in doc.items)


def test_weltbau_tx1() -> None:
    doc = parse_pdf(sample("ДОО350-ДОН-ПИР-П-ТХ1.pdf"))
    assert len([p for p in doc.pages if p.kind == "spec"]) == 74
    assert len(doc.items) == 784
    assert len(doc.summary) == 136
    stul = next(s for s in doc.summary if s.pos == "2.10")
    assert stul.qty > 100 and len(stul.groups) > 5
    assert not any(i.warnings for i in doc.items)


def test_avalon_d300() -> None:
    doc = parse_pdf(sample("Д300_1_2023_ТХ_Выдано_в_производство_работ РД Пищ+ТХ.pdf"))
    assert doc.doc_code == "ДОО300/1-2023-ТХ"
    assert len([p for p in doc.pages if p.kind == "spec"]) == 26
    assert len(doc.items) == 221
    assert {i.group for i in doc.items} == {"ФУНКЦИОНАЛ", "ПИЩЕБЛОК"}
    first = doc.items[0]
    assert first.pos == "1,1" and first.pos_key == "1.1" and first.qty == 14
    # штамп «В производство работ» не должен попадать в примечания
    assert not any("ГЛОБАЛСТРОЙТЕХ" in i.note or "Июнь" in i.note for i in doc.items)
