from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from datetime import date, timedelta

from app.export.excel import build_workbook
from app.export.kp import round_half_up
from app.main import app, price_lists
from app.models import ExportRequest, HistoryCandidate, HistoryPrice, HistoryPurchase, Indexation, KpSettings, SummaryItem
from app.pricing.indexation import indexation_factor

client = TestClient(app)


def _history() -> HistoryPrice:
    best = HistoryCandidate(key="стул детский", name="Стул детский регулируемый", score=1.0, price_min=950, price_max=2600, price_median=1725, price_last=2600, last_date="2025-05-27", purchases=19)
    return HistoryPrice(kind="exact", best=best, candidates=[best], purchases=[HistoryPurchase(purchased_at="2025-05-27", unit_price=2600, qty=26, partner_item="Стул «Малыш»", order="БАУТ-1")], matched_at="2026-09-25")


def test_cost_workbook_has_three_price_columns_and_choice() -> None:
    data = ExportRequest(
        title="ДОО на 350 мест",
        kind="cost",
        summary=[
            SummaryItem(pos="2.10", section="Мебель", name="Стул детский", description="Стул детский регулируемый", unit="шт.", qty=364, price=950, price_source="history_min", history=_history()),
            SummaryItem(pos="7.48", section="Оборудование пищеблока", name="Шкаф холодильный", description="700 л", unit="шт.", qty=1, price=None, history=HistoryPrice(kind="none")),
        ],
    )
    wb = build_workbook(data)
    assert wb.sheetnames == ["Себестоимость", "Покупки по истории"]
    ws = wb["Себестоимость"]
    heads = [ws.cell(2, c).value for c in range(1, 18)]
    assert heads[7] == "Цена интернет на дату" and heads[9] == "Цена минимальная по истории закупок" and heads[10] == "Цена максимальная по истории закупок"
    assert (ws["J3"].value, ws["K3"].value, ws["L3"].value, ws["M3"].value) == (950, 2600, 2600, "2025-05-27")
    assert ws["N3"].value.startswith("точно: Стул детский регулируемый")
    assert (ws["O3"].value, ws["P3"].value, ws["Q3"].value) == (950, "мин. история", "=F3*O3")
    assert ws["N4"].value == "не найдено" and ws["O4"].value is None
    assert ws["Q5"].value == "=SUM(Q3:Q4)"
    hist = wb["Покупки по истории"]
    assert hist["D2"].value == "Стул детский регулируемый" and hist["F2"].value == 2600
    buffer = io.BytesIO()
    wb.save(buffer)
    load_workbook(io.BytesIO(buffer.getvalue()))


def test_cost_sheet_indexes_prices_to_delivery_date() -> None:
    delivery = (date.today() + timedelta(days=365)).isoformat()
    data = ExportRequest(
        title="Объект",
        kind="cost",
        indexation=Indexation(date=delivery, rates={"Мебель": 5.0, "": 3.0}),
        summary=[
            SummaryItem(pos="1", section="Мебель", name="Стул", unit="шт.", qty=10, price=1000),
            SummaryItem(pos="2", section="Пищеблок", name="Плита", unit="шт.", qty=1, price=50000),
            SummaryItem(pos="3", section="Мебель", name="Без цены", unit="шт.", qty=1, price=None),
        ],
    )
    wb = build_workbook(data)
    ws = wb["Себестоимость"]
    assert (ws.cell(2, 18).value, ws.cell(2, 19).value, ws.cell(2, 20).value) == ("Индексация, % в год", f"Цена на {delivery}", f"Стоимость на {delivery}")
    assert ws["R3"].value == 5.0 and ws["S3"].value.startswith("=ROUND(O3*(1+R3/100)^") and ws["T3"].value == "=F3*S3"
    assert ws["R4"].value == 3.0  # раздела «Пищеблок» в ставках нет — общая
    assert ws["S5"].value is None and ws["T5"].value is None  # без цены нечего индексировать
    assert (ws["S6"].value, ws["T6"].value) == (f"Итого на {delivery}", "=SUM(T3:T5)")
    assert "проиндексированы" in ws["A1"].value
    # Без даты — прежние 17 граф.
    plain = build_workbook(ExportRequest(kind="cost", summary=[SummaryItem(pos="1", name="Стул", qty=1, price=1)]))["Себестоимость"]
    assert plain.cell(2, 18).value is None and plain.auto_filter.ref.startswith("A2:Q")


def test_kp_uses_indexed_base_price_when_asked() -> None:
    delivery = date.today() + timedelta(days=365)
    kp = KpSettings()
    item = SummaryItem(pos="1", section="Мебель", name="Стул", unit="шт.", qty=2, price=1000, installation=False)
    with_indexation = ExportRequest(kind="kp", kp=kp, indexation=Indexation(date=delivery.isoformat(), rates={"": 10.0}, apply_to_kp=True), summary=[item])
    without = ExportRequest(kind="kp", kp=kp, indexation=Indexation(date=delivery.isoformat(), rates={"": 10.0}, apply_to_kp=False), summary=[item])

    def price_cell(request: ExportRequest) -> float:
        ws = build_workbook(request)["2"]
        row = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == 1)
        return ws.cell(row, 11).value  # графа K листа «2» — цена за ед. с НДС

    expected = round_half_up(1000 * indexation_factor(10.0, date.today(), delivery), 2)
    assert price_cell(with_indexation) == expected and 1090 < expected < 1101
    assert price_cell(without) == 1000


def test_export_kind_defaults_keep_old_behaviour() -> None:
    assert ExportRequest().resolved_kind() == "working"
    assert ExportRequest(kp={}).resolved_kind() == "kp"
    assert ExportRequest(kp={}, kind="cost").resolved_kind() == "cost"


def test_pricelist_endpoints(tmp_path: Path, history_xlsx: Path) -> None:
    price_lists.data_dir = tmp_path
    price_lists.path = tmp_path / "pricelist.json"
    price_lists.price_list = price_lists.matcher = None
    try:
        assert client.get("/api/pricelist").status_code == 404
        assert client.post("/api/pricelist/match", json={"items": [{"id": "a", "name": "Стул"}]}).status_code == 409

        with history_xlsx.open("rb") as f:
            r = client.post("/api/pricelist", files={"file": ("история.xlsx", f, "application/octet-stream")})
        assert r.status_code == 200, r.text
        info = r.json()
        assert info["entries"] == 3 and info["rows_total"] == 8 and info["period_from"] == "2023-02-10"
        assert (tmp_path / "pricelist.json").exists()
        assert client.get("/api/pricelist").json()["source"] == "история.xlsx"
        assert client.get("/api/health").json()["pricelist"] is True

        r = client.post("/api/pricelist/match", json={"items": [{"id": "1", "name": "Стул детский регулируемый"}, {"id": "2", "name": "Проектор"}]})
        assert r.status_code == 200
        matches = r.json()["matches"]
        assert matches["1"]["kind"] == "exact" and matches["1"]["best"]["price_min"] == 1000.0 and len(matches["1"]["purchases"]) == 4
        assert matches["2"]["kind"] == "none" and matches["2"]["best"] is None

        r = client.post("/api/pricelist", files={"file": ("файл.txt", b"x", "text/plain")})
        assert r.status_code == 400
    finally:
        price_lists.price_list = price_lists.matcher = None
