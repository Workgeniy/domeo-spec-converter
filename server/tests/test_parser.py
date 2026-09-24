from __future__ import annotations

from pathlib import Path

import pymupdf

from app.parsing.geometry import Word
from app.parsing.ocr import TesseractProvider, detect_rules, ocr_page
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
    """Скан проходит общий конвейер: слова от OCR, линии — с растра."""
    text_words = read_page(pymupdf.open(synthetic_spec_pdf)[0], 1).words

    class FakeOcr:
        name = "fake"

        def recognize(self, pixmap: pymupdf.Pixmap) -> list[Word]:
            k = pixmap.width / 842
            return [Word(w.x0 * k, w.y0 * k, w.x1 * k, w.y1 * k, w.text) for w in text_words]

    doc = parse_pdf(synthetic_scan_pdf, ocr=FakeOcr())
    assert doc.pages[0].source == "ocr"
    assert doc.pages[0].kind == "spec"
    assert [i.pos for i in doc.items] == ["2.1", "2.10", "б/н"]
    assert doc.items[1].qty == 26


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
