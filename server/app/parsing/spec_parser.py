"""Разбор документа целиком: страницы -> строки таблицы -> позиции спецификации."""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from ..models import PageInfo, ParsedDocument, SpecItem
from .aggregate import build_summary
from .geometry import PageData
from .ocr import OcrProvider, default_provider, ocr_page
from .pdf_reader import open_document, read_page
from .table import Row, detect_layout, extract_rows

POS_RE = re.compile(r"^\d{1,3}[.,]\d{1,4}(?:[.,]\d{1,3})?[а-яa-zА-Я]?$")
# Позиции без номера («б/н», «б/п») и буквенные марки инженерного оборудования («ВН», «ТЗ»).
NO_POS_RE = re.compile(r"^(?:б[/\\][нп]|[А-ЯA-Z]{1,4}\d{0,3})$")
ROOM_POS_RE = re.compile(r"^\d{1,2}\.\d{2}$")
QTY_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
DOC_CODE_RE = re.compile(r"[А-ЯA-Z0-9]{2,}[А-ЯA-Z0-9/_-]*-ТХ\d*(?:\.\d+)?")
TITLE_RE = re.compile(r"[«\"]([^«»\"]{15,300})[»\"]")


def parse_pdf(
    source: str | Path | bytes,
    file_name: str | None = None,
    ocr: OcrProvider | None = None,
) -> ParsedDocument:
    doc = open_document(source)
    name = file_name or (Path(source).name if not isinstance(source, (bytes, bytearray)) else "документ.pdf")
    result = ParsedDocument(file_name=name)
    ocr = ocr or default_provider()

    items: list[SpecItem] = []
    current_group = ""
    first_page_texts: list[str] = []

    for index, page in enumerate(doc):
        number = index + 1
        data = read_page(page, number)
        info = PageInfo(number=number)

        if not data.has_text_layer:
            if data.image_coverage < 0.3 and not data.words:
                info.source = "skipped"
                result.pages.append(info)
                continue
            if ocr is None:
                info.source = "skipped"
                info.warnings.append("страница похожа на скан, а OCR недоступен (не установлен Tesseract)")
                result.pages.append(info)
                continue
            data = ocr_page(page, number, ocr)
            info.source = "ocr"

        if number <= 4:
            first_page_texts.append(" ".join(w.text for w in data.words))

        layout = detect_layout(data)
        if layout is None:
            result.pages.append(info)
            continue

        info.kind = "spec"
        info.warnings.extend(layout.warnings)
        rows = extract_rows(data, layout)
        page_items, current_group = _rows_to_items(rows, number, current_group, items, len(items))
        items.extend(page_items)
        info.rows = len(page_items)
        result.pages.append(info)
        _collect_spec_title(data, result)

    result.items = items
    result.summary = build_summary(items)
    _fill_metadata(result, first_page_texts, name)
    default_section = _default_section(result.spec_title)
    for summary in result.summary:
        summary.section = summary.section or default_section
    if not any(p.kind == "spec" for p in result.pages):
        result.warnings.append("в документе не найдено ни одной страницы со спецификацией")
    return result


def _rows_to_items(
    rows: list[Row], page: int, group: str, previous: list[SpecItem], next_id: int
) -> tuple[list[SpecItem], str]:
    items: list[SpecItem] = []
    for row_index, row in enumerate(rows):
        pos = row.cells.get("pos", "").strip()
        name = row.cells.get("name", "").strip()
        unit = row.cells.get("unit", "").strip()
        qty_raw = row.cells.get("qty", "").strip()

        if not name and not pos:
            continue
        # Строка без единицы и количества — заголовок группы (помещение или раздел)
        # либо продолжение описания с прошлой страницы.
        if not unit and not qty_raw:
            last = (items or previous)[-1] if (items or previous) else None
            if row_index == 0 and not pos and last is not None and name and name[:1].islower():
                last.description = f"{last.description} {name}".strip()
                last.warnings.append(f"описание продолжено со стр. {page}")
                continue
            group = f"{pos} {name}".strip()
            continue

        item = SpecItem(
            id=next_id + len(items) + 1,
            page=page,
            pos=pos,
            pos_key=normalize_pos(pos),
            description=name,
            name=short_name(name),
            type_mark=row.cells.get("type_mark", "") or row.cells.get("doc", ""),
            code=row.cells.get("code", ""),
            manufacturer=row.cells.get("manufacturer", ""),
            unit=unit,
            qty_raw=qty_raw,
            mass=row.cells.get("mass", ""),
            note=row.cells.get("note", ""),
            group=group,
        )
        item.qty = parse_qty(qty_raw)
        if item.qty is None:
            item.warnings.append(f"не удалось прочитать количество: «{qty_raw}»")
        if not pos:
            item.warnings.append("нет номера позиции")
        elif not (POS_RE.match(pos) or NO_POS_RE.match(pos)):
            item.warnings.append(f"необычный номер позиции: «{pos}»")
        if not name:
            item.warnings.append("пустое наименование")
        if not unit:
            item.warnings.append("нет единицы измерения")
        items.append(item)
    return items, group


def normalize_pos(pos: str) -> str:
    return pos.replace(",", ".").replace(" ", "").lower()


def parse_qty(raw: str) -> float | None:
    raw = raw.replace(" ", "")
    if not QTY_RE.match(raw):
        return None
    return float(raw.replace(",", "."))


def short_name(description: str, min_len: int = 8, max_len: int = 90) -> str:
    """Краткое наименование: первое предложение или фраза до запятой."""
    if not description:
        return ""
    parts = re.split(r"(?<=[.;])\s+|,\s+", description)
    name = ""
    for part in parts:
        name = f"{name}, {part}" if name else part
        if len(name) >= min_len:
            break
    name = name.rstrip(".;, ")
    if len(name) > max_len:
        name = name[:max_len].rsplit(" ", 1)[0] + "…"
    return name


def _default_section(spec_title: str) -> str:
    """«Раздел» для КП, когда в самой таблице разделов нет (только помещения)."""
    if "пищеблок" in spec_title.lower():
        return "Оборудование пищеблока"
    return ""


def _collect_spec_title(data: PageData, result: ParsedDocument) -> None:
    if result.spec_title:
        return
    text = " ".join(w.text for w in data.words)
    m = re.search(r"Спецификация\s+технологического\s+оборудования(?:\s+[а-яё]+)?", text)
    if m:
        result.spec_title = m.group(0)


def _fill_metadata(result: ParsedDocument, texts: list[str], file_name: str) -> None:
    joined = " ".join(texts)
    m = DOC_CODE_RE.search(joined)
    result.doc_code = m.group(0) if m else Path(file_name).stem
    m = TITLE_RE.search(joined)
    if m:
        result.title = re.sub(r"\s+", " ", m.group(1)).strip()
