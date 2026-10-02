from __future__ import annotations

from app.export.excel import build_workbook
from app.models import ExportRequest, SourceDocument, SummaryItem
from app.parsing.aggregate import cross_volume_duplicates


def _item(pos: str, name: str, doc: str, qty: float | None = 1, description: str = "") -> SummaryItem:
    return SummaryItem(pos=pos, name=name, description=description or name, unit="шт.", qty=qty, source_doc=doc)


def test_cross_volume_duplicates_match_by_name_not_position() -> None:
    summary = [
        _item("7.124", "Стол производственный", "ТХ1", 2, "Стол производственный, нерж., 1000х600"),
        _item("3.10", "Стол производственный", "ТХ2", 1, "Стол производственный, нерж., 1000х600"),
        _item("1.1", "Стул офисный", "ТХ1", 5),  # тот же номер в разных томах, но разные вещи — не дубль
        _item("1.1", "Стул детский", "ТХ2", 10),
        _item("2.2", "Мойка", "ТХ1", 1),  # есть только в одном томе — не дубль
    ]
    groups = cross_volume_duplicates(summary)
    assert len(groups) == 1
    group = groups[0]
    assert {s.source_doc for s in group} == {"ТХ1", "ТХ2"} and [s.pos for s in group] == ["7.124", "3.10"]


def test_single_document_has_no_cross_volume_duplicates() -> None:
    # В одном томе повторы уже сведены; одинаковые наименования с одним source_doc не в счёт.
    summary = [_item("1", "Стол", "ТХ1"), _item("2", "Стол", "ТХ1")]
    assert cross_volume_duplicates(summary) == []


def test_check_sheet_lists_cross_volume_duplicates() -> None:
    data = ExportRequest(
        title="Объект",
        kind="working",
        summary=[
            _item("7.124", "Стол производственный", "ДОО-ТХ1", 2),
            _item("3.10", "Стол производственный", "ДОО-ТХ2", 1),
        ],
        documents=[SourceDocument(doc_code="ДОО-ТХ1", file_name="тх1.pdf"), SourceDocument(doc_code="ДОО-ТХ2", file_name="тх2.pdf")],
    )
    ws = build_workbook(data)["Проверка"]
    texts = [str(c.value) for row in ws.iter_rows(values_only=True) for c in [type("C", (), {"value": v})() for v in row] if c.value]
    joined = " | ".join(texts)
    assert "Совпадающие позиции между томами" in joined
    assert "ДОО-ТХ1, поз. 7.124 — 2 шт." in joined and "ДОО-ТХ2, поз. 3.10 — 1 шт." in joined


def test_check_sheet_without_duplicates_has_no_section() -> None:
    data = ExportRequest(
        title="Объект",
        kind="working",
        summary=[_item("1", "Стол", "ТХ1"), _item("2", "Стул", "ТХ2")],
        documents=[SourceDocument(doc_code="ТХ1"), SourceDocument(doc_code="ТХ2")],
    )
    ws = build_workbook(data)["Проверка"]
    joined = " ".join(str(v) for row in ws.iter_rows(values_only=True) for v in row if v)
    assert "Совпадающие позиции между томами" not in joined
