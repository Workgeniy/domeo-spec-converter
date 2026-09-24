from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import app

client = TestClient(app)


def test_health() -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_parse_and_export_roundtrip(synthetic_spec_pdf: Path) -> None:
    with synthetic_spec_pdf.open("rb") as f:
        r = client.post("/api/parse", files={"file": ("spec.pdf", f, "application/pdf")})
    assert r.status_code == 200, r.text
    parsed = r.json()
    assert len(parsed["items"]) == 3
    assert len(parsed["documents"]) == 1 and parsed["documents"][0]["rows"] == 3
    assert parsed["items"][0]["source_doc"] == parsed["doc_code"]

    # Менеджер проставил цену и поправил раздел — Excel собирается из присланных данных.
    parsed["summary"][1]["price"] = 1234.5
    parsed["summary"][1]["section"] = "Мебель"
    r = client.post("/api/export", json=parsed)
    assert r.status_code == 200
    assert "spec.xlsx" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Спецификация", "По помещениям", "Проверка"]
    ws = wb["Спецификация"]
    assert ws["C3"].value == "Наименование"
    assert ws["G5"].value == "2.10" and ws["F5"].value == 26
    assert ws["B5"].value == "Мебель" and ws["M5"].value == 1234.5 and ws["M4"].value is None
    assert ws["H5"].value == "=J5/(1+L5)" and ws["N5"].value == "=F5*M5"
    assert ws["N7"].value == "=SUM(N4:N6)"
    detail = wb["По помещениям"]
    assert detail["B1"].value == "Документ" and detail["B2"].value == parsed["doc_code"]
    check = wb["Проверка"]
    labels = [check.cell(i, 1).value for i in range(1, 20)]
    assert "Позиций с ценой" in labels and "Документ" in labels


def test_rejects_non_pdf() -> None:
    r = client.post("/api/parse", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400
