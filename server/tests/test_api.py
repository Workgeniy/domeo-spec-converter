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

    r = client.post("/api/export", json=parsed)
    assert r.status_code == 200
    assert "spec.xlsx" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Спецификация", "По помещениям", "Проверка"]
    ws = wb["Спецификация"]
    assert ws["C3"].value == "Наименование"
    assert ws["G5"].value == "2.10" and ws["F5"].value == 26
    assert ws["H5"].value == "=J5/(1+L5)" and ws["N5"].value == "=F5*M5"
    assert ws["N7"].value == "=SUM(N4:N6)"


def test_rejects_non_pdf() -> None:
    r = client.post("/api/parse", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400
