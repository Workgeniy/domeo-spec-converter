from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, indexation_rates
from app.pricing.indexation import IndexationStore, history_indexation, indexation_factor, rate_for, years_between
from app.pricing.pricelist import PriceEntry, PriceList, Purchase

client = TestClient(app)


def test_store_and_endpoints(tmp_path: Path) -> None:
    store = IndexationStore(data_dir=tmp_path)
    store.set_rates([])
    saved = (indexation_rates.data_dir, indexation_rates.path, dict(indexation_rates._rates))
    indexation_rates.data_dir, indexation_rates.path = tmp_path, tmp_path / "indexation.json"
    indexation_rates._rates = {}
    try:
        info = client.get("/api/indexation").json()
        assert info["rates"] == [] and "history" in info
        put = client.put("/api/indexation", json={"rates": [{"section": " Мебель ", "rate": 5, "source": "history", "note": "по истории 2024–2026"}, {"section": "", "rate": 3.5, "source": "official", "note": "ИПЦ"}]})
        assert put.status_code == 200
        rates = put.json()["rates"]
        assert [(r["section"], r["rate"], r["source"]) for r in rates] == [("Мебель", 5.0, "history"), ("", 3.5, "official")]
        assert rates[0]["updated_at"]
        assert client.put("/api/indexation", json={"rates": [{"section": "Мебель", "rate": 500}]}).status_code == 422
        assert json.loads((tmp_path / "indexation.json").read_text(encoding="utf-8"))["rates"][0]["section"] in ("Мебель", "")
        reloaded = IndexationStore(data_dir=tmp_path)
        reloaded.load()
        assert reloaded.as_dict() == {"Мебель": 5.0, "": 3.5}
    finally:
        indexation_rates.data_dir, indexation_rates.path, indexation_rates._rates = saved


def _entry(name: str, group: str, prices_by_year: dict[int, list[float]], outlier_year: int | None = None) -> PriceEntry:
    purchases = [
        Purchase(purchased_at=date(year, 6, 1), unit_price=price, qty=1, outlier=(year == outlier_year))
        for year, prices in prices_by_year.items()
        for price in prices
    ]
    return PriceEntry(key=name.lower(), name=name, group=group, purchases=purchases)


def test_history_rates_by_group_and_overall() -> None:
    entries = [_entry(f"Стул {i}", "Мебель", {2023: [1000], 2024: [1050, 1070], 2025: [1102.4]}) for i in range(12)]  # +6%, +4%
    entries += [_entry(f"Мяч {i}", "Спорт", {2024: [500], 2025: [600]}) for i in range(4)]  # мало сравнений
    entries += [_entry("Странный", "Мебель", {2024: [100], 2025: [5000]})]  # ×50 — не индексация, мимо
    entries += [_entry("Выброс", "Мебель", {2024: [1000], 2025: [1000]}, outlier_year=2025)]  # выброс не считается
    result = history_indexation(PriceList(source="t", built_at="2026-09-28", rows_total=0, entries=entries), today=date(2026, 9, 28))
    furniture = next(g for g in result.groups if g.group == "Мебель")
    assert furniture.samples == 24 and furniture.rate == 5.0  # медиана изменений +6 % и +4 %
    assert [(p.years, p.rate, p.samples) for p in furniture.pairs] == [("2023→2024", 6.0, 12), ("2024→2025", 4.0, 12)]
    sport = next(g for g in result.groups if g.group == "Спорт")
    assert sport.rate is None and sport.samples == 4  # меньше 10 сравнений — ставки нет
    assert result.overall is not None and result.overall.samples == 28 and result.overall.rate is not None
    assert result.computed_at == "2026-09-28"
    assert history_indexation(PriceList(source="t", built_at="2026-09-28", rows_total=0, entries=[])).overall is None


def test_factor_and_rate_lookup() -> None:
    assert years_between(date(2026, 9, 28), date(2027, 9, 28)) == 365 / 365.25
    assert years_between(date(2026, 9, 28), date(2026, 1, 1)) == 0  # в прошлое не индексируем
    assert round(indexation_factor(10, date(2026, 1, 1), date(2027, 1, 1)), 3) == 1.1  # 365 дней ≈ год
    assert round(indexation_factor(10, date(2026, 1, 1), date(2026, 7, 2)), 4) == round(1.1 ** (182 / 365.25), 4)
    assert indexation_factor(10, date(2026, 1, 1), date(2025, 1, 1)) == 1.0
    rates = {"Мебель": 5.0, "": 3.5}
    assert rate_for("Мебель", rates) == 5.0 and rate_for("мебель ", rates) == 5.0
    assert rate_for("Пищеблок", rates) == 3.5
    assert rate_for("Пищеблок", {"Мебель": 5.0}) is None
