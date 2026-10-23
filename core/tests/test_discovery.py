from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.main import app, internet_prices, supplier_index
from app.models import SearchParam
from app.pricing.internet import AutoSearchProvider
from app.pricing.suppliers.crawler import CrawlResult
from app.pricing.suppliers.discovery import WebPriceSearch, build_query, is_shop_candidate, room_context, site_name_of
from app.pricing.suppliers.extract import Extracted
from app.pricing.suppliers.index import SupplierIndex
from app.pricing.websearch import SearchHit

client = TestClient(app)

PRODUCT = """<html><head><title>Стул детский регулируемый по высоте №1-№3 — Мебель-Сад</title><meta property="og:site_name" content="Мебель-Сад">
<script type="application/ld+json">{"@type":"Product","name":"Стул детский регулируемый по высоте №1-№3","offers":{"@type":"Offer","price":"1 350","priceCurrency":"RUB"}}</script>
</head><body><h1>Стул детский</h1></body></html>"""
PRODUCT2 = """<html><head><title>Стул детский регулируемый №1-3 | Парта-Плюс</title>
<script type="application/ld+json">{"@type":"Product","name":"Стул детский регулируемый по высоте №1-№3, бук","offers":{"@type":"Offer","price":"1 490","priceCurrency":"RUB"}}</script>
</head><body></body></html>"""
NO_PRICE = "<html><head><title>Статья про стулья — Блог</title></head><body><h1>Как выбрать стул</h1><p>текст</p></body></html>"


class FakeEngine:
    name = "fake-search"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, max_results: int = 8) -> list[SearchHit]:
        self.queries.append(query)
        return [
            SearchHit(url="https://www.ozon.ru/category/stul/", title="Ozon"),  # маркетплейс — мимо
            SearchHit(url="https://mebel-sad.test/catalog/stul-13", title="Стул детский"),
            SearchHit(url="https://parta-plus.test/product/stul", title="Стул детский регулируемый"),
            SearchHit(url="https://blog.test/kak-vybrat-stul", title="Как выбрать стул"),
            SearchHit(url="https://closed.test/product/1", title="Закрыто robots"),
            SearchHit(url="https://mebel-sad.test/files/price.pdf", title="Прайс"),
        ]


def _client(requests: list[str]) -> httpx.Client:
    pages = {
        "https://mebel-sad.test/robots.txt": ("text/plain", "User-agent: *\nDisallow: /files/\n"),
        "https://mebel-sad.test/catalog/stul-13": ("text/html", PRODUCT),
        "https://parta-plus.test/product/stul": ("text/html", PRODUCT2),
        "https://blog.test/kak-vybrat-stul": ("text/html", NO_PRICE),
        "https://closed.test/robots.txt": ("text/plain", "User-agent: *\nDisallow: /\n"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        page = pages.get(str(request.url))
        if page is None:
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": page[0]}, content=page[1].encode("utf-8"))

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


class ParamAwareEngine(FakeEngine):
    """Запрос с размерами ничего не находит, без них — обычная выдача."""

    def search(self, query: str, max_results: int = 8) -> list[SearchHit]:
        if "x" in query:
            self.queries.append(query)
            return []
        return super().search(query, max_results)


def test_query_prefers_human_query_then_falls_back_to_sizes(tmp_path: Path) -> None:
    # Сначала короткий «человеческий» запрос (название + помещение, без габаритов): на бесплатном
    # поиске длинный запрос с габаритами часто не находит ничего. Габариты — как уточнение дальше.
    index = SupplierIndex(data_dir=tmp_path)
    index.set_settings(autocrawl_pages=0)
    engine = ParamAwareEngine()  # запрос с габаритами («…x…») ничего не находит, без них — обычная выдача
    web = WebPriceSearch(engine, index, data_dir=tmp_path, client=_client([]), page_delay=0)
    pages = web.find("Стул детский регулируемый по высоте №1-№3", "Стул детский, 350х340х260/300/340(h)", "шт.", "2026-09-25", section="ДОО — групповая")
    assert engine.queries[0] == "Стул детский регулируемый по высоте №1-№3 групповая купить"  # название + помещение, без габаритов
    assert [p.host for p in pages if p.offers] == ["mebel-sad.test", "parta-plus.test"]
    assert web.cached_queries == 1

    # Если по короткому запросу пусто — в ход идут габариты.
    class RoomEmpty(FakeEngine):
        def search(self, query: str, max_results: int = 8) -> list[SearchHit]:
            self.queries.append(query)
            return [] if "x" not in query else FakeEngine().search(query, max_results)

    e2 = RoomEmpty()
    web2 = WebPriceSearch(e2, index, data_dir=tmp_path / "d2", client=_client([]), page_delay=0)
    web2.find("Стул детский регулируемый по высоте №1-№3", "Стул детский, 350х340х260/300/340(h)", "шт.", "2026-09-25")
    assert e2.queries[0] == "Стул детский регулируемый по высоте №1-№3 купить"  # человеческий — пусто
    assert e2.queries[1] == "Стул детский регулируемый по высоте №1-№3 350x340x260 купить"  # габариты


def test_helpers() -> None:
    assert build_query("  Стул   детский ") == "Стул детский купить"
    assert build_query("Стеллаж с перфорированными полками", "Стеллаж, 2000х1000х400(h), 4 полки") == "Стеллаж с перфорированными полками 2000x1000x400 купить"
    # Помещение из спецификации уточняет неоднозначное название.
    assert build_query("Музыкальный центр", "", "", "музыкальный зал") == "Музыкальный центр музыкальный зал купить"
    # room_context убирает код объекта в начале раздела (он сузил бы выдачу), оставляет помещение.
    assert room_context("ДОО — музыкальный зал") == "музыкальный зал"
    assert room_context("ДОУ: пищеблок") == "пищеблок" and room_context("Школа — спортивный зал") == "спортивный зал"
    assert room_context("Мебель") == "Мебель" and room_context("ДОО —") == "" and room_context("") == ""
    assert is_shop_candidate("https://mebel-sad.test/catalog/1") and not is_shop_candidate("https://www.ozon.ru/x") and not is_shop_candidate("https://a.test/f.pdf")
    assert site_name_of(PRODUCT) == "Мебель-Сад" and site_name_of(PRODUCT2) == "Парта-Плюс" and site_name_of("<html><title>Просто</title></html>") == ""
    # Хвост заголовка-слогана — не имя магазина: возьмут хост.
    assert site_name_of("<html><title>Мойка — купить мойку из нержавеющей стали от производителя</title></html>") == ""
    assert site_name_of("<html><title>Шкаф | Холодильный шкаф 700 л, 0…+6 °C</title></html>") == ""


def test_room_context_goes_into_web_query(tmp_path: Path) -> None:
    index = SupplierIndex(data_dir=tmp_path)
    index.set_settings(autocrawl_pages=0, min_shops=5)
    engine = FakeEngine()
    web = WebPriceSearch(engine, index, data_dir=tmp_path, client=_client([]), page_delay=0)
    web.find("Музыкальный центр", "", "шт.", "2026-10-23", section="ДОО — музыкальный зал")
    assert engine.queries[0] == "Музыкальный центр музыкальный зал купить"  # помещение — в первом запросе
    # Через авто-провайдер помещение тоже доходит до поисковика.
    engine2 = FakeEngine()
    web2 = WebPriceSearch(engine2, index, data_dir=tmp_path / "b", client=_client([]), page_delay=0)
    AutoSearchProvider(index, web2).lookup("Музыкальный центр", "", "шт.", "2026-10-23", section="ДОО — музыкальный зал")
    assert engine2.queries and "музыкальный зал" in engine2.queries[0]


def test_web_search_fills_index_and_caches(tmp_path: Path) -> None:
    index = SupplierIndex(data_dir=tmp_path)
    index.set_settings(autocrawl_pages=0)  # без автообхода
    engine = FakeEngine()
    requests: list[str] = []
    web = WebPriceSearch(engine, index, data_dir=tmp_path, client=_client(requests), page_delay=0)
    pages = web.find("Стул детский регулируемый по высоте №1-№3", "", "шт.", "2026-09-25")
    assert [p.host for p in pages if p.offers] == ["mebel-sad.test", "parta-plus.test"]
    assert "https://closed.test/product/1" not in requests and "https://www.ozon.ru/category/stul/" not in requests
    assert "https://mebel-sad.test/files/price.pdf" not in requests

    info = index.info()
    assert info.offers == 2 and sorted(s.name for s in info.suppliers) == ["Мебель-Сад", "Парта-Плюс"]
    found = next(s for s in info.suppliers if s.name == "Мебель-Сад")
    assert found.discovered and found.site == "https://mebel-sad.test" and found.query.endswith("купить") and found.status == "done"
    assert (tmp_path / "web_search_cache.json").exists() and web.cached_queries == 1

    # Повтор той же позиции — из кэша, поисковик и сайты не трогаются.
    before = len(requests)
    web.find("Стул детский регулируемый по высоте №1-№3", "", "шт.", "2026-09-25")
    assert engine.queries == ["Стул детский регулируемый по высоте №1-№3 купить"] and len(requests) == before
    assert index.info().offers == 2  # дубли не добавились

    reloaded = WebPriceSearch(FakeEngine(), index, data_dir=tmp_path, client=_client([]), page_delay=0)
    reloaded.load()
    assert reloaded.cached_queries == 1


def test_auto_provider_searches_web_until_enough_shops(tmp_path: Path) -> None:
    index = SupplierIndex(data_dir=tmp_path)
    index.set_settings(autocrawl_pages=0, min_shops=3)
    engine = FakeEngine()
    web = WebPriceSearch(engine, index, data_dir=tmp_path, client=_client([]), page_delay=0)
    provider = AutoSearchProvider(index, web)
    assert "меньше 3 магазинов" in provider.model

    lookup = provider.lookup("Стул детский регулируемый по высоте №1-№3", "", "шт.", "2026-09-25")
    assert lookup.status == "found" and lookup.provider == "auto" and lookup.price == 1420  # медиана 1350 и 1490
    assert sorted(o.shop for o in lookup.offers) == ["Мебель-Сад", "Парта-Плюс"]
    assert engine.queries == ["Стул детский регулируемый по высоте №1-№3 купить"]

    # Магазинов всё ещё два (< 3): поисковик нужен, но тот же запрос идёт из кэша поиска.
    again = provider.lookup("Стул детский регулируемый по высоте №1-№3", "", "шт.", "2026-09-25")
    assert again.price == 1420 and len(engine.queries) == 1 and "новых магазинов не нашёл" in again.comment

    # Свежий кэш поиска: при пороге 3 поисковик спрашивают снова, при пороге 2 — уже нет.
    fresh = WebPriceSearch(engine, index, data_dir=tmp_path / "fresh", client=_client([]), page_delay=0)
    AutoSearchProvider(index, fresh).lookup("Стул детский регулируемый по высоте №1-№3", "", "шт.", "2026-09-25")
    assert len(engine.queries) == 2
    index.set_settings(min_shops=2)
    fresh2 = WebPriceSearch(engine, index, data_dir=tmp_path / "fresh2", client=_client([]), page_delay=0)
    enough = AutoSearchProvider(index, fresh2).lookup("Стул детский регулируемый по высоте №1-№3", "", "шт.", "2026-09-25")
    assert len(engine.queries) == 2 and enough.price == 1420 and "автопоиск" not in enough.comment

    # Ничего не нашлось ни в индексе, ни в интернете — честное «не найдено» с пояснением.
    class EmptyEngine:
        name = "empty"

        def search(self, query: str, max_results: int = 8) -> list[SearchHit]:
            return []

    nothing = AutoSearchProvider(index, WebPriceSearch(EmptyEngine(), index, data_dir=tmp_path, client=_client([]), page_delay=0))
    miss = nothing.lookup("Шкаф холодильный 700 л", "", "шт.", "2026-09-25")
    assert miss.status == "not_found" and "автопоиск" in miss.comment

    # Поисковик упал — ответ индекса с пометкой, без исключения.
    class BrokenEngine:
        name = "broken"

        def search(self, query: str, max_results: int = 8) -> list[SearchHit]:
            raise RuntimeError("ratelimit")

    broken = AutoSearchProvider(index, WebPriceSearch(BrokenEngine(), index, data_dir=tmp_path, client=_client([]), page_delay=0))
    assert "не ответил" in broken.lookup("Ножничный подъёмник", "", "шт.", "2026-09-25").comment


def test_auto_provider_uses_operator_params(tmp_path: Path) -> None:
    index = SupplierIndex(data_dir=tmp_path)
    index.set_settings(autocrawl_pages=0, min_shops=1)
    engine = FakeEngine()
    provider = AutoSearchProvider(index, WebPriceSearch(engine, index, data_dir=tmp_path, client=_client([]), page_delay=0))
    beech = [SearchParam(name="Материал", value="бук")]
    # Параметр оператора — в запросе поисковику; цена — по предложению, где он подтверждён.
    lookup = provider.lookup("Стул детский регулируемый по высоте №1-№3", "", "шт.", "2026-10-01", params=beech)
    assert engine.queries == ["Стул детский регулируемый по высоте №1-№3 бук купить"]
    assert lookup.price == 1490 and "с заданными параметрами совпадений 1" in lookup.comment
    # Подтвердивший магазин уже есть (порог 1) — в интернет больше не идём.
    provider.lookup("Стул детский регулируемый по высоте №1-№3", "", "шт.", "2026-10-01", params=beech)
    assert len(engine.queries) == 1
    # Металл не подтверждён нигде: магазины «с тем же стулом» не в счёт — поиск идёт, цена по всем с пометкой.
    metal = provider.lookup("Стул детский регулируемый по высоте №1-№3", "", "шт.", "2026-10-01", params=[SearchParam(name="Каркас", value="металл")])
    assert engine.queries[1] == "Стул детский регулируемый по высоте №1-№3 каркас металл купить"
    assert metal.price == 1420 and "не подтверждены" in metal.comment and "новых магазинов не нашёл" in metal.comment
    # Без параметров — как раньше, по названию.
    assert build_query("Стул детский", "", "") == "Стул детский купить"


FRIDGE = """<html><head><title>Шкаф холодильный Polair CM107-S — ХолодОпт</title>
<script type="application/ld+json">{"@type":"Product","name":"Шкаф холодильный Polair CM107-S","offers":{"@type":"Offer","price":"79 900","priceCurrency":"RUB"}}</script>
</head><body></body></html>"""


class ModelEngine:
    """Находит страницу только по модели из проекта."""

    name = "fake-search"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, max_results: int = 8) -> list[SearchHit]:
        self.queries.append(query)
        return [SearchHit(url="https://holod-opt.test/cm107s", title="Polair CM107-S")] if "CM107-S" in query else []


def test_auto_provider_searches_reference_model_first(tmp_path: Path) -> None:
    index = SupplierIndex(data_dir=tmp_path)
    index.set_settings(autocrawl_pages=0, min_shops=1)
    shop = index.add("Кухни-Про", "kuhni.test")
    index.set_offers(shop.id, [Extracted(name="Шкаф холодильный среднетемпературный Carboma R700", price=82000)], "карта сайта")
    pages = {"https://holod-opt.test/cm107s": FRIDGE, "https://holod-opt.test/robots.txt": ""}

    def handler(request: httpx.Request) -> httpx.Response:
        body = pages.get(str(request.url))
        return httpx.Response(200, headers={"content-type": "text/html"}, content=body.encode("utf-8")) if body is not None else httpx.Response(404)

    engine = ModelEngine()
    web = WebPriceSearch(engine, index, data_dir=tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)), page_delay=0)
    provider = AutoSearchProvider(index, web)
    name = "Шкаф холодильный среднетемпературный"
    # Похожих магазинов хватает (порог 1), но модели из проекта в индексе нет — ищем её, и цена по ней.
    lookup = provider.lookup(name, "", "шт.", "2026-10-01", type_mark="по типу Polair CM107-S")
    assert engine.queries == ["шкаф Polair CM107-S купить"]
    assert lookup.price == 79900 and lookup.offers[0].note.startswith("модель как в проекте")
    # Модель уже в индексе — в интернет не идём; без модели в проекте — как раньше.
    provider.lookup(name, "", "шт.", "2026-10-01", type_mark="по типу Polair CM107-S")
    provider.lookup(name, "", "шт.", "2026-10-01")
    assert len(engine.queries) == 1


BOILER = """<html><head><title>Кипятильник Atesy Фонтан АКНЭ-100 — ПроКухня</title>
<script type="application/ld+json">{"@type":"Product","name":"Кипятильник Atesy Фонтан АКНЭ-100","offers":{"@type":"Offer","price":"63 489","priceCurrency":"RUB"}}</script>
</head><body></body></html>"""


class ModelOnlyEngine:
    """По общему названию ничего нет, по модели из истории закупок — страница магазина."""

    name = "fake-search"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, max_results: int = 8) -> list[SearchHit]:
        self.queries.append(query)
        if "АКНЭ-100" in query:
            return [SearchHit(url="https://prokuhnya.test/aknje-100", title="Кипятильник АКНЭ-100")]
        return []


def test_auto_provider_searches_names_from_history(tmp_path: Path) -> None:
    index = SupplierIndex(data_dir=tmp_path)
    index.set_settings(autocrawl_pages=0, min_shops=1)
    pages = {"https://prokuhnya.test/aknje-100": BOILER, "https://prokuhnya.test/robots.txt": ""}

    def handler(request: httpx.Request) -> httpx.Response:
        body = pages.get(str(request.url))
        return httpx.Response(200, headers={"content-type": "text/html"}, content=body.encode("utf-8")) if body is not None else httpx.Response(404)

    engine = ModelOnlyEngine()
    web = WebPriceSearch(engine, index, data_dir=tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)), page_delay=0)
    provider = AutoSearchProvider(index, web, market_names=lambda name, description: ["Кипятильник Фонтан АКНЭ-100"])
    lookup = provider.lookup("Кипятильник электрический", "", "шт.", "2026-09-29")
    # Сначала — по нашему названию; магазинов не хватило — по названию, под которым покупали раньше.
    assert engine.queries == ["Кипятильник электрический купить", "Кипятильник Фонтан АКНЭ-100 купить"]
    assert lookup.price == 63489 and "по названию из истории закупок" in lookup.offers[0].note
    # Магазин уже в индексе: повторный поиск в интернет не ходит.
    again = provider.lookup("Кипятильник электрический", "", "шт.", "2026-09-29")
    assert again.price == 63489 and len(engine.queries) == 2
    # Сбой сопоставления с историей поиск не ломает.
    broken = AutoSearchProvider(index, web, market_names=lambda name, description: 1 / 0)
    assert broken.lookup("Кипятильник электрический", "", "шт.", "2026-09-29").price is None


class FakeCrawler:
    def __init__(self, **kwargs):
        pass

    def crawl(self, site: str) -> CrawlResult:
        return CrawlResult(offers=[Extracted(name="Стол воспитателя", price=6800, url=f"{site}/p/stol")], pages=1, source="карта сайта")


def test_discovered_supplier_is_queued_for_crawl_and_keeps_search_offers(tmp_path: Path) -> None:
    index = SupplierIndex(data_dir=tmp_path)
    index._crawler_factory = lambda **kw: FakeCrawler(**kw)
    index.set_settings(autocrawl_pages=200)
    web = WebPriceSearch(FakeEngine(), index, data_dir=tmp_path, client=_client([]), page_delay=0)
    web.find("Стул детский регулируемый по высоте №1-№3", "", "шт.", "2026-09-25")
    for supplier in index.info().suppliers:
        index.wait(supplier.id, timeout=10)
    info = index.info()
    assert info.queued == 0 and all(s.crawled and s.status == "done" for s in info.suppliers)
    mebel = next(s for s in info.suppliers if s.name == "Мебель-Сад")
    names = sorted(o.name for o in index.offers[mebel.id])
    assert names == ["Стол воспитателя", "Стул детский регулируемый по высоте №1-№3"]  # обход + страница из поиска
    assert mebel.max_pages == 200 and mebel.source.startswith("карта сайта")


def test_settings_endpoint_and_info(tmp_path: Path) -> None:
    saved = (supplier_index.dir, supplier_index.autocrawl_pages, supplier_index.min_shops)
    supplier_index.dir = tmp_path / "suppliers"
    try:
        response = client.put("/api/suppliers/settings", json={"autocrawl_pages": 120, "min_shops": 4})
        assert response.status_code == 200 and response.json()["autocrawl_pages"] == 120 and response.json()["min_shops"] == 4
        assert client.put("/api/suppliers/settings", json={"autocrawl_pages": -1}).status_code == 422
        assert client.put("/api/suppliers/settings", json={"min_shops": 0}).status_code == 422
        info = client.get("/api/suppliers").json()
        assert info["autocrawl_pages"] == 120 and info["min_shops"] == 4 and "search_engine" in info
        saved_file = json.loads((tmp_path / "suppliers" / "index.json").read_text(encoding="utf-8"))
        assert saved_file["autocrawl_pages"] == 120 and saved_file["min_shops"] == 4
        assert internet_prices.provider is not None and internet_prices.provider.name in ("auto", "suppliers", "fake", "claude-web-search")
    finally:
        supplier_index.dir, supplier_index.autocrawl_pages, supplier_index.min_shops = saved
