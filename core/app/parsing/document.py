"""Разбор спецификации из файла: PDF или Excel — по расширению."""

from __future__ import annotations

from pathlib import Path

from ..models import ParsedDocument
from .ocr import OcrProvider
from .spec_parser import parse_pdf
from .xlsx_spec import parse_xlsx

XLSX_SUFFIXES = (".xlsx", ".xlsm")


def is_supported(file_name: str) -> bool:
    name = file_name.lower()
    return name.endswith(".pdf") or name.endswith(XLSX_SUFFIXES)


def parse_document(source: str | Path | bytes, file_name: str | None = None, ocr: OcrProvider | None = None) -> ParsedDocument:
    """PDF — через parse_pdf (разбор по геометрии, при необходимости OCR), Excel — через
    parse_xlsx (столбцы по шапке). Расширение берётся из file_name, иначе из пути."""
    name = file_name or (Path(source).name if not isinstance(source, (bytes, bytearray)) else "")
    if name.lower().endswith(XLSX_SUFFIXES):
        return parse_xlsx(source, file_name=name)
    return parse_pdf(source, file_name=name, ocr=ocr)
