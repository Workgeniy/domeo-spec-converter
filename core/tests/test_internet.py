from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.export.excel import build_workbook
from app.main import app, internet_prices
from app.models import ExportRequest, InternetLookup, InternetOffer, MatchRequestItem, SearchParam, SummaryItem
from app.pricing.internet import InternetPriceService, extract_json, parse_lookup, today_moscow

client = TestClient(app)


class FakeProvider:
    """Подставной поиск: по имени позиции — найдено / не найдено / ошибка."""

    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def lookup(self, name: str, description: str, unit: str, today: str, section: str = "", params=()) -> InternetLookup:
        self.calls.append(name)
        if "нет" in name.lower():
            return InternetLookup(status="not_found", query=name, looked_up_at=today, provider=self.name, comment="ничего похожего")
        if "ошибка" in name.lower():
            raise RuntimeError("сеть упала")
        offers = [
            InternetOffer(title=f"{name} — точный", url="https://shop.example/1", shop="Магазин", price=1200),
            InternetOffer(title="похожий товар", url="https://shop.example/2", shop="Другой", price=1500, analog=True, note="без ящиков"),
        ]
        return InternetLookup(status="found", query=name, looked_up_at=today, offers=offers, price=1200, provider=self.name, searches=2)


def test_extract_json_handles_fences_and_prose() -> None:
    assert extract_json('Вот ответ:\n```json\n{"price": 10, "offers": []}\n```\nконец')["price"] == 10
    assert extract_json('{"a": {"b": 1}} хвост')["a"]["b"] == 1
    with pytest.raises(ValueError):
        extract_json("ничего не нашёл")


def test_parse_lookup_filters_bad_offers_and_takes_median() -> None:
    payload = {
        "offers": [
            {"title": "A", "url": "https://a", "shop": "A", "price": "1 200,50 ₽"},
            {"title": "B", "url": "https://b", "shop": "B", "price": 900},
            {"title": "C", "url": "https://c", "shop": "C", "price": 3000, "analog": True},
            {"title": "мусор", "price": "нет"},
            "не словарь",
        ],
        "price": None,
        "comment": "нашлось два точных",
    }
    lookup = parse_lookup(payload, query="стул", today="2026-09-25", provider="fake", searches=3)
    assert lookup.status == "found" and len(lookup.offers) == 3 and lookup.searches == 3
    assert lookup.offers[0].price == 1200.5 and lookup.offers[2].analog
    assert lookup.price == 1200.5  # медиана по точным (900, 1200.5) — верхняя средняя
    assert parse_lookup({"offers": [], "price": 0}, query="q", today="2026-09-25", provider="fake").status == "not_found"


def test_service_caches_dedupes_and_does_not_cache_errors(tmp_path: Path) -> None:
    provider = FakeProvider()
    service = InternetPriceService(provider, data_dir=tmp_path, ttl_days=7)
    items = [
        MatchRequestItem(id="a", name="Стул детский", description="регулируемый"),
        MatchRequestItem(id="b", name="Стул детский", description="регулируемый"),  # та же позиция — один запрос
        MatchRequestItem(id="c", name="Нет такого", description=""),
        MatchRequestItem(id="d", name="Ошибка сети", description=""),
    ]
    result = service.lookup_many(items)
    assert result["a"].status == "found" and result["a"].price == 1200
    assert result["b"] is result["a"] or result["b"].price == 1200
    assert result["c"].status == "not_found"
    assert result["d"].status == "error" and "сеть упала" in result["d"].comment
    assert provider.calls == ["Стул детский", "Нет такого", "Ошибка сети"]
    assert (tmp_path / "internet_prices.json").exists()
    assert service.info().cached == 2  # ошибка в кэш не попала

    # Повтор: найденное и «не найдено» берутся из кэша, ошибка ищется снова.
    again = service.lookup_many(items)
    assert provider.calls == ["Стул детский", "Нет такого", "Ошибка сети", "Ошибка сети"]
    assert again["a"].looked_up_at == today_moscow()

    # refresh=True — всё заново; кэш переживает перезапуск сервиса.
    service.lookup_many(items[:1], refresh=True)
    assert provider.calls[-1] == "Стул детский"
    reloaded = InternetPriceService(FakeProvider(), data_dir=tmp_path)
    reloaded.load()
    assert reloaded.cached("Стул детский", "регулируемый") is not None
    assert reloaded.cached("Стул детский", "регулируемый", today="2027-01-01") is None  # протухло

    class OtherProvider(FakeProvider):
        name = "other"

    other = InternetPriceService(OtherProvider(), data_dir=tmp_path)
    other.load()
    assert other.cached("Стул детский", "регулируемый") is None  # найденное другим провайдером (заглушкой) не годится


def test_service_passes_operator_params_and_keys_cache_by_them(tmp_path: Path) -> None:
    class Recording(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.params: list[list[tuple[str, str]]] = []

        def lookup(self, name: str, description: str, unit: str, today: str, section: str = "", params=()) -> InternetLookup:
            self.params.append([(p.name, p.value) for p in params])
            return super().lookup(name, description, unit, today, section, params)

    provider = Recording()
    service = InternetPriceService(provider, data_dir=tmp_path)
    legs = [SearchParam(name="Материал ножек", value="металл"), SearchParam(name="Цвет", value=" ")]  # пустое — отброшено
    plain = service.lookup_many([MatchRequestItem(id="a", name="Стол обеденный")])["a"]
    with_params = service.lookup_many([MatchRequestItem(id="b", name="Стол обеденный", search_params=legs)])["b"]
    assert plain.params == [] and [(p.name, p.value) for p in with_params.params] == [("Материал ножек", "металл")]
    assert provider.params == [[], [("Материал ножек", "металл")]]  # другие параметры — другой поиск, не из кэша
    # Те же параметры в другом регистре — из кэша; без параметров — прежняя запись.
    same = [SearchParam(name="материал ножек", value="Металл")]
    assert service.lookup_many([MatchRequestItem(id="c", name="Стол обеденный", search_params=same)])["c"].params == with_params.params
    assert service.lookup_many([MatchRequestItem(id="d", name="Стол обеденный")])["d"].params == []
    assert len(provider.params) == 2


def test_internet_endpoints(tmp_path: Path) -> None:
    saved = (internet_prices.provider, internet_prices.data_dir, internet_prices.path)
    internet_prices.provider = None
    internet_prices.data_dir = tmp_path
    internet_prices.path = tmp_path / "internet_prices.json"
    try:
        info = client.get("/api/internet")
        assert info.status_code == 200 and info.json()["configured"] is False
        assert client.post("/api/internet/lookup", json={"items": [{"id": "a", "name": "Стул"}]}).status_code == 409

        internet_prices.provider = FakeProvider()
        info = client.get("/api/internet").json()
        assert info["configured"] is True and info["model"] == "fake-model"
        too_many = {"items": [{"id": str(i), "name": f"Позиция {i}"} for i in range(51)]}
        assert client.post("/api/internet/lookup", json=too_many).status_code == 400
        response = client.post("/api/internet/lookup", json={"items": [{"id": "d1:0", "name": "Стул детский", "description": "рег.", "unit": "шт."}, {"id": "d1:1", "name": "Нет"}]})
        assert response.status_code == 200
        lookups = response.json()["lookups"]
        assert lookups["d1:0"]["status"] == "found" and lookups["d1:0"]["offers"][0]["url"] == "https://shop.example/1"
        assert lookups["d1:1"]["status"] == "not_found"
        assert lookups["d1:0"]["params"] == []
        assert json.loads((tmp_path / "internet_prices.json").read_text(encoding="utf-8"))["lookups"]
        with_params = {"items": [{"id": "d1:2", "name": "Стол обеденный", "search_params": [{"name": "Материал", "value": "металл"}]}]}
        assert client.post("/api/internet/lookup", json=with_params).json()["lookups"]["d1:2"]["params"] == [{"name": "Материал", "value": "металл"}]
    finally:
        internet_prices.provider, internet_prices.data_dir, internet_prices.path = saved
        internet_prices._cache.clear()


def test_from_env_fake_provider_is_marked_as_test_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PRICE_SEARCH_PROVIDER", "fake")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    service = InternetPriceService.from_env()
    assert service.configured and service.info().model == "тестовые данные"
    lookup = service.lookup_many([MatchRequestItem(id="a", name="Стул детский", unit="шт.")])["a"]
    assert lookup.status == "found" and lookup.offers and "тестов" in lookup.comment.lower()
    assert all("тестов" in (o.title + o.shop).lower() for o in lookup.offers)

    monkeypatch.delenv("PRICE_SEARCH_PROVIDER")
    assert not InternetPriceService.from_env().configured


def test_cost_export_writes_internet_offers_sheet() -> None:
    lookup = FakeProvider().lookup("Стул детский", "", "шт.", "2026-09-25")
    data = ExportRequest(
        title="Объект",
        kind="cost",
        summary=[
            SummaryItem(pos="2.10", name="Стул детский", unit="шт.", qty=10, price=1200, price_source="internet", internet=lookup, internet_price=1200, internet_source="https://shop.example/1", internet_date="2026-09-25"),
            SummaryItem(pos="2.11", name="Нет такого", unit="шт.", qty=1, internet=InternetLookup(status="not_found", looked_up_at="2026-09-25", comment="ничего")),
            SummaryItem(
                pos="2.12",
                name="Стол обеденный",
                unit="шт.",
                qty=1,
                search_params=[SearchParam(name="Материал ножек", value="металл")],
                internet=lookup.model_copy(update={"params": [SearchParam(name="Материал ножек", value="металл")]}),
            ),
        ],
    )
    wb = build_workbook(data)
    assert wb.sheetnames == ["Себестоимость", "Покупки по истории", "Предложения из интернета"]
    ws = wb["Себестоимость"]
    assert ws["H3"].value == 1200 and ws["I3"].value == "2026-09-25 · Магазин" and ws["I3"].hyperlink.target == "https://shop.example/1"
    assert ws["P3"].value == "интернет"
    offers = wb["Предложения из интернета"]
    assert (offers["F2"].value, offers["G2"].value, offers["I2"].hyperlink.target) == ("Стул детский — точный", 1200, "https://shop.example/1")
    assert offers["H3"].value == "да" and offers["F4"].value == "не найдено"
    # С какими параметрами оператора искали — строкой перед предложениями позиции.
    assert offers["F5"].value == "Параметры поиска: материал ножек — металл" and offers["C5"].value == "Стол обеденный"
    buffer = io.BytesIO()
    wb.save(buffer)
    load_workbook(io.BytesIO(buffer.getvalue()))
