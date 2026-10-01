from __future__ import annotations

import gzip
import io
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app, internet_prices, supplier_index
from app.models import SearchParam
from app.pricing.internet import SupplierIndexProvider
from app.pricing.suppliers.crawler import CrawlResult, SiteCrawler, normalize_site
from app.pricing.suppliers.extract import Extracted, extract_offers, looks_like_listing, parse_price, parse_sitemap, parse_yml, product_name
from app.pricing.suppliers.index import SupplierIndex
from app.pricing.suppliers.xlsx_import import read_price_list

client = TestClient(app)

JSONLD_PAGE = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Стул детский регулируемый №1-3","sku":"SD-13",
 "offers":{"@type":"Offer","price":"1 250,00","priceCurrency":"RUB","url":"https://shop.test/p/1"}}
</script></head><body><h1>Стул детский</h1><div class="price">999 ₽</div></body></html>"""
MICRODATA_PAGE = """<html><body><div itemscope itemtype="http://schema.org/Product"><span itemprop="name">Стол воспитателя</span>
<div itemprop="offers" itemscope itemtype="http://schema.org/Offer"><meta itemprop="priceCurrency" content="RUB"><span itemprop="price" content="6800">6 800 ₽</span></div></div></body></html>"""
OG_PAGE = """<html><head><meta property="og:title" content="Тележка грузовая платформенная"><meta property="product:price:amount" content="13535.90">
<meta property="product:price:currency" content="RUB"></head><body></body></html>"""
HEURISTIC_PAGE = """<html><body><h1>Мольберт двусторонний</h1><div class="product-price">9 800 руб.</div></body></html>"""
PLAIN_PAGE = """<html><body><h1>О компании</h1><p>Мы работаем с 2005 года. 100 сотрудников.</p></body></html>"""
USD_PAGE = """<html><head><script type="application/ld+json">{"@type":"Product","name":"Импортный стол","offers":{"@type":"Offer","price":"120","priceCurrency":"USD"}}</script></head></html>"""
YML = """<?xml version="1.0" encoding="UTF-8"?><yml_catalog date="2026-09-25"><shop><name>Магазин</name><currencies><currency id="RUR" rate="1"/></currencies>
<offers><offer id="1"><name>Тумба мобильная на 4 ячейки</name><price>5400</price><currencyId>RUR</currencyId><url>https://shop.test/t4</url><vendorCode>TM-4</vendorCode></offer>
<offer id="2"><vendor>Ника</vendor><model>Доска магнитно-маркерная</model><price>8 029,80</price><currencyId>RUR</currencyId><url>https://shop.test/d1</url></offer>
<offer id="3"><name>Чужая валюта</name><price>10</price><currencyId>USD</currencyId></offer></offers></shop></yml_catalog>""".encode("utf-8")


def test_parse_price_variants() -> None:
    assert parse_price("12 345,60 ₽") == 12345.6
    assert parse_price("от 990 руб.") == 990
    assert parse_price("1 250") == 1250
    assert parse_price(6800) == 6800
    assert parse_price("нет в наличии") is None and parse_price(0) is None and parse_price(True) is None


def test_extract_prefers_markup_over_heuristic() -> None:
    jsonld = extract_offers(JSONLD_PAGE, "https://shop.test/page")
    assert [(o.name, o.price, o.sku, o.url, o.source) for o in jsonld] == [("Стул детский регулируемый №1-3", 1250.0, "SD-13", "https://shop.test/p/1", "jsonld")]
    micro = extract_offers(MICRODATA_PAGE, "https://shop.test/p/2")
    assert (micro[0].name, micro[0].price, micro[0].source) == ("Стол воспитателя", 6800.0, "microdata")
    og = extract_offers(OG_PAGE, "https://shop.test/p/3")
    assert (og[0].name, og[0].price, og[0].source) == ("Тележка грузовая платформенная", 13535.9, "og")
    heuristic = extract_offers(HEURISTIC_PAGE, "https://shop.test/p/4")
    assert (heuristic[0].name, heuristic[0].price, heuristic[0].source) == ("Мольберт двусторонний", 9800.0, "heuristic")
    assert extract_offers(PLAIN_PAGE, "https://shop.test/about") == []
    assert extract_offers(USD_PAGE, "https://shop.test/p/5") == []
    # Страница категории: один h1 и много цен — эвристика молчит, чтобы не приписать h1 чужую цену.
    listing = "<html><body><h1>Стулья для детского сада</h1>" + "".join(f'<div class="price">{p} ₽</div>' for p in (1495, 1600, 1750, 1990, 2100)) + "</body></html>"
    assert extract_offers(listing, "https://shop.test/catalog/stulya") == []
    # Относительная ссылка в разметке становится абсолютной.
    relative = MICRODATA_PAGE.replace('<span itemprop="name">', '<a itemprop="url" href="/katalog/stol-vospitatelya"></a><span itemprop="name">')
    assert extract_offers(relative, "https://shop.test/katalog/")[0].url == "https://shop.test/katalog/stol-vospitatelya"


def test_parse_yml_and_sitemap() -> None:
    offers = parse_yml(YML)
    assert [(o.name, o.price, o.sku) for o in offers] == [("Тумба мобильная на 4 ячейки", 5400.0, "TM-4"), ("Ника Доска магнитно-маркерная", 8029.8, "")]
    assert parse_yml(gzip.compress(YML))[0].url == "https://shop.test/t4"
    index = b'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://shop.test/sitemap-1.xml</loc></sitemap></sitemapindex>'
    urls = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://shop.test/product/1</loc><lastmod>2026-01-01</lastmod></url><url><loc>https://shop.test/news/1</loc></url></urlset>'
    assert parse_sitemap(index) == ("index", ["https://shop.test/sitemap-1.xml"])
    assert parse_sitemap(urls) == ("urls", ["https://shop.test/product/1", "https://shop.test/news/1"])
    assert parse_sitemap(b"<html>no</html>") == ("", []) and parse_sitemap(b"garbage") == ("", [])


def _price_list(path: Path, with_header: bool = True) -> Path:
    wb = Workbook()
    ws = wb.active
    if with_header:
        ws.append(["ООО Поставщик", None, None, None])
        ws.append(["Прайс-лист от 01.09.2026", None, None, None])
        ws.append(["Артикул", "Наименование товара", "Ед.", "Цена с НДС, руб."])
        ws.append(["ST-1", "Стол трапециевидный двухместный регулируемый", "шт.", 3100])
        ws.append(["ST-2", "Стул детский регулируемый по высоте", "шт.", "950,00"])
        ws.append([None, "Итого", None, None])
    else:
        ws.append(["Мольберт двусторонний напольный", 9800])
        ws.append(["Тележка для спортинвентаря", 9800])
        ws.append(["Комплект модулей для хранения игрушек", 25000])
    wb.save(path)
    return path


def test_read_price_list_with_and_without_header(tmp_path: Path) -> None:
    offers = read_price_list(_price_list(tmp_path / "прайс.xlsx"))
    assert [(o.name, o.price, o.sku) for o in offers] == [("Стол трапециевидный двухместный регулируемый", 3100.0, "ST-1"), ("Стул детский регулируемый по высоте", 950.0, "ST-2")]
    guessed = read_price_list(_price_list(tmp_path / "без шапки.xlsx", with_header=False))
    assert len(guessed) == 3 and guessed[0].price == 9800


def _mock_site(requests: list[str]):
    """Сайт с robots.txt, картой сайта, карточками с разметкой и закрытым разделом."""
    pages = {
        "https://shop.test/robots.txt": ("text/plain", "User-agent: *\nDisallow: /private/\nSitemap: https://shop.test/sitemap.xml\n"),
        "https://shop.test/sitemap.xml": ("application/xml", '<sitemapindex xmlns="x"><sitemap><loc>https://shop.test/sitemap-products.xml</loc></sitemap></sitemapindex>'),
        "https://shop.test/sitemap-products.xml": (
            "application/xml",
            '<urlset xmlns="x"><url><loc>https://shop.test/news/1</loc></url><url><loc>https://shop.test/product/1</loc></url>'
            '<url><loc>https://shop.test/product/2</loc></url><url><loc>https://shop.test/private/3</loc></url><url><loc>https://other.test/product/9</loc></url></urlset>',
        ),
        "https://shop.test/product/1": ("text/html", JSONLD_PAGE),
        "https://shop.test/product/2": ("text/html", MICRODATA_PAGE),
        "https://shop.test/private/3": ("text/html", OG_PAGE),
        "https://feed.test/robots.txt": ("text/plain", ""),
        "https://feed.test/yml.xml": ("application/xml", YML.decode("utf-8")),
        "https://spider.test/robots.txt": ("text/plain", ""),
        "https://spider.test/": ("text/html", '<html><body><a href="/catalog/a">A</a><a href="/about/">о нас</a><a href="https://ext.test/x">x</a></body></html>'),
        "https://spider.test/catalog/a": ("text/html", HEURISTIC_PAGE + '<a href="/catalog/b">B</a>'),
        "https://spider.test/catalog/b": ("text/html", OG_PAGE),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        page = pages.get(str(request.url))
        if page is None:
            return httpx.Response(404)
        content_type, body = page
        return httpx.Response(200, headers={"content-type": content_type}, content=body.encode("utf-8"))

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_crawler_sitemap_yml_and_spider() -> None:
    requests: list[str] = []
    crawler = SiteCrawler(client=_mock_site(requests), delay=0, max_pages=50)
    result = crawler.crawl("shop.test")
    assert sorted(o.name for o in result.offers) == ["Стол воспитателя", "Стул детский регулируемый №1-3"]
    assert result.pages == 2 and result.source.startswith("карта сайта")
    assert "https://shop.test/private/3" not in requests and "https://shop.test/news/1" not in requests

    feed = SiteCrawler(client=_mock_site([]), delay=0).crawl("https://feed.test")
    assert len(feed.offers) == 2 and feed.source.startswith("фид YML")

    spider = SiteCrawler(client=_mock_site([]), delay=0, max_pages=10).crawl("https://spider.test/")
    assert sorted(o.name for o in spider.offers) == ["Мольберт двусторонний", "Тележка грузовая платформенная"]
    assert spider.source == "переходы по ссылкам"

    assert SiteCrawler(client=_mock_site([]), delay=0).crawl("https://nowhere.test").error
    assert normalize_site("Shop.Test/catalog") == "https://shop.test"
    with pytest.raises(ValueError):
        normalize_site("просто текст")


class FakeCrawler:
    def __init__(self, **kwargs):
        self.progress = kwargs["progress"]

    def crawl(self, site: str) -> CrawlResult:
        self.progress("страниц 3 из 3, цен 3")
        return CrawlResult(
            offers=[
                Extracted(name="Стул детский регулируемый по высоте №1-№3", price=1300, url=f"{site}/p1", sku="S1"),
                Extracted(name="Стул детский регулируемый по высоте №1-№3, бук", price=1500, url=f"{site}/p2"),
                Extracted(name="Стул офисный на металлическом каркасе", price=2200, url=f"{site}/p3"),
                Extracted(name="Стул детский регулируемый по высоте №1-№3", price=1300, url=f"{site}/catalog/page2"),  # тот же товар с другой страницы
            ],
            pages=3,
            source="карта сайта https://a.test/sitemap.xml",
        )


def test_index_crawl_lookup_and_persistence(tmp_path: Path) -> None:
    index = SupplierIndex(data_dir=tmp_path)
    index._crawler_factory = lambda **kw: FakeCrawler(**kw)
    a = index.add("Поставщик А", "a.test")
    b = index.add("Поставщик Б")
    assert (a.kind, a.site, b.kind) == ("site", "https://a.test", "pricelist")
    with pytest.raises(ValueError):
        index.start_crawl(b.id)
    index.start_crawl(a.id)
    index.wait(a.id, timeout=10)
    done = index.get(a.id)
    assert (done.status, done.offers, done.source) == ("done", 3, "карта сайта https://a.test/sitemap.xml")  # дубль отброшен
    assert index.info().offers == 3 and index.sample(a.id, limit=2)[0].supplier == "Поставщик А"

    found = index.lookup("Стул детский регулируемый по высоте №1-№3", "", "шт.", "2026-09-25")
    assert found.status == "found" and found.provider == "suppliers"
    assert [o.analog for o in found.offers][:2] == [False, False] and found.price == 1400  # медиана двух совпадений
    assert found.offers[0].shop == "Поставщик А" and "совпадение" in found.offers[0].note
    weak = index.lookup("Стул офисный", "", "шт.", "2026-09-25")
    assert weak.status == "found" and weak.price is not None
    assert index.lookup("Шкаф холодильный 700 л", "", "шт.", "2026-09-25").status == "not_found"

    reloaded = SupplierIndex(data_dir=tmp_path)
    reloaded.load()
    assert reloaded.info().offers == 3 and reloaded.get(a.id).status == "done"
    reloaded.remove(a.id)
    assert reloaded.info().offers == 0 and not (tmp_path / "suppliers" / "offers" / f"{a.id}.json").exists()


def test_parameters_separate_sizes(tmp_path: Path) -> None:
    index = SupplierIndex(data_dir=tmp_path)
    shop = index.add("Металл-Пром", "metprommebel.ru")
    index.set_offers(
        shop.id,
        [
            Extracted(name="Стеллаж 2000x1000x400 с 4 перфорированными полками", price=10180, url="https://metprommebel.ru/1"),
            Extracted(name="Стеллаж 2500x1000x400 с 4 перфорированными полками", price=10764, url="https://metprommebel.ru/2"),
            Extracted(name="Стеллаж 2000x1000x500 с 4 перфорированными полками", price=11992, url="https://metprommebel.ru/3"),
            Extracted(name="Стеллаж с перфорированными полками, 4 полки", price=9000, url="https://metprommebel.ru/4"),  # размер не указан
        ],
        "карта сайта",
    )
    # Без характеристик все четыре — та же позиция, медиана по всем.
    plain = index.lookup("Стеллаж с перфорированными полками тип 2", "", "шт.", "2026-09-25")
    assert [o.analog for o in plain.offers] == [False] * 4 and plain.price == (10180 + 10764) / 2
    # С размером в характеристиках: другой размер — «похоже», в цену не входит.
    sized = index.lookup("Стеллаж с перфорированными полками тип 2", "Стеллаж металлический, 4 полки, 2000х1000х400(h)", "шт.", "2026-09-25")
    by_title = {o.title: o for o in sized.offers}
    assert not by_title["Стеллаж 2000x1000x400 с 4 перфорированными полками"].analog and "параметры совпали" in by_title["Стеллаж 2000x1000x400 с 4 перфорированными полками"].note
    assert by_title["Стеллаж 2500x1000x400 с 4 перфорированными полками"].analog and "параметры не совпали" in by_title["Стеллаж 2500x1000x400 с 4 перфорированными полками"].note
    assert by_title["Стеллаж 2000x1000x500 с 4 перфорированными полками"].analog
    # Число полок совпало, размера у продавца нет — в цене, но с пометкой «совпали не все».
    assert not by_title["Стеллаж с перфорированными полками, 4 полки"].analog and "совпали не все" in by_title["Стеллаж с перфорированными полками, 4 полки"].note
    assert sized.price == (9000 + 10180) / 2 and sized.comment.startswith("параметры 2000x1000x400 полок 4;")
    assert sized.offers[0].title.startswith("Стеллаж 2000x1000x400")  # совпавший размер — первым
    # Только чужие размеры: цены нет, оператору честно сказано почему.
    other = index.lookup("Стеллаж 2500x1000x400", "2500х1000х400(h)", "шт.", "2026-09-25")
    assert other.price is not None  # 2500-й совпал по словам и по размеру
    # Размер, которого нет ни у кого: в цену попадает только предложение без размера, с просьбой проверить.
    unknown = index.lookup("Стеллаж с перфорированными полками", "3000х1200х600(h)", "шт.", "2026-09-25")
    assert unknown.status == "found" and unknown.price == 9000 and "параметры не указаны" in unknown.offers[0].note
    assert "проверьте размер" in unknown.comment and [o.analog for o in unknown.offers[1:]] == [True, True, True]


def test_listing_titles_and_page_tails() -> None:
    assert looks_like_listing("Диваны в Хабаровске") and looks_like_listing("Скамьи для раздевалок купить от производителя")
    assert looks_like_listing("Главная") and not looks_like_listing("Мыло жидкое в флаконе") and not looks_like_listing("Шкаф для каталогов")
    assert product_name("Наушники - Учебные материалы | Учебное оборудование для школ") == "Наушники"
    assert product_name("Перегородка - стеллаж на металлическом каркасе | Сайт") == "Перегородка - стеллаж на металлическом каркасе"
    assert product_name("Стул ИЗО, ткань") == "Стул ИЗО, ткань"


def test_same_item_rules(tmp_path: Path) -> None:
    index = SupplierIndex(data_dir=tmp_path)
    shop = index.add("Магазин", "shop.test")
    index.set_offers(
        shop.id,
        [
            Extracted(name="Стулья с пюпитром", price=9900),  # раздел каталога: множественное число
            Extracted(name="Стул с пюпитром ИЗО, ткань черная", price=5200),
            Extracted(name="Столы", price=3500),  # раздел: одно слово
            Extracted(name="Перегородка - стеллаж на металлическом каркасе", price=219000),  # другое главное слово
            Extracted(name="Стеллаж металлический МС-1", price=6100),
            Extracted(name="Стулья на металлическом каркасе в Челябинске", price=3600),  # SEO-заголовок
            Extracted(name="Наушники - Учебные материалы | Учебное оборудование для школ", price=1200),  # хвост заголовка
            Extracted(name="Посудомоечная машина фронтальная", price=1),  # «1 ₽» — цена по запросу
            Extracted(name="Ванна котломоечная односекционная ВК-1", price=31180),
            Extracted(name="Кипятильник Atesy Фонтан АКНЭ-100", price=63489),
            Extracted(name="Стол, цвет белый", price=18321),
        ],
        "карта сайта",
    )
    chair = index.lookup("Стул с пюпитром", "", "шт.", "2026-09-29")
    assert chair.price == 5200 and [(o.title, o.analog) for o in chair.offers] == [("Стул с пюпитром ИЗО, ткань черная", False), ("Стулья с пюпитром", True)]
    assert index.lookup("Стол воспитателя", "", "шт.", "2026-09-29").price is None
    assert index.lookup("Стеллаж металлический", "", "шт.", "2026-09-29").price == 6100
    assert index.lookup("Наушники", "", "шт.", "2026-09-29").price == 1200
    assert index.lookup("Посудомоечная машина", "", "шт.", "2026-09-29").status == "not_found"
    assert index.lookup("Ванна котломоечная двухсекционная", "", "шт.", "2026-09-29").price is None  # число секций другое
    # По нашему названию кипятильника нет, по названию из истории закупок — есть, с пометкой.
    assert index.lookup("Кипятильник электрический", "", "шт.", "2026-09-29").price is None
    boiler = index.lookup("Кипятильник электрический", "", "шт.", "2026-09-29", aliases=["Кипятильник Фонтан АКНЭ-100"])
    assert boiler.price == 63489 and "по названию из истории закупок «Кипятильник Фонтан АКНЭ-100»" in boiler.offers[0].note
    # Предложение без единого общего слова с нашим названием по чужому названию не засчитывается.
    sink = index.lookup("Тумба медицинская с двойной мойкой", "", "шт.", "2026-09-29", aliases=["Стол-мойка медицинский, цвет белый"])
    assert sink.status == "not_found"


def test_operator_params_pick_offers_and_price(tmp_path: Path) -> None:
    index = SupplierIndex(data_dir=tmp_path)
    shop = index.add("Мебель-Опт", "mebel-opt.test")
    other = index.add("Столы-Стулья", "stoly.test")
    index.set_offers(
        shop.id,
        [
            Extracted(name="Стол обеденный, столешница ЛДСП, ножки металл", price=9000),
            Extracted(name="Стол обеденный на металлических ножках", price=11000),
            Extracted(name="Стол обеденный деревянный", price=7000),
        ],
        "карта сайта",
    )
    index.set_offers(other.id, [Extracted(name="Стол обеденный Masey", price=8000)], "карта сайта")
    # Без параметров — медиана по всем четырём.
    assert index.lookup("Стол обеденный", "", "шт.", "2026-10-01").price == 8500
    # Ножки металл: подтверждено у двух — цена по ним; деревянный и Masey в цену не вошли.
    legs = [SearchParam(name="Материал ножек", value="металл")]
    lookup = index.lookup("Стол обеденный", "", "шт.", "2026-10-01", params=legs)
    assert lookup.price == 10000 and lookup.comment.startswith("параметры оператора: материал ножек — металл; с заданными параметрами совпадений 2")
    assert "ещё 2 без подтверждения" in lookup.comment
    # Подтвердившие — первыми (при равном совпадении — дешёвые раньше).
    assert [o.title for o in lookup.offers[:2]] == ["Стол обеденный, столешница ЛДСП, ножки металл", "Стол обеденный на металлических ножках"]
    # Материал целиком: деревянный стол — противоречие, уходит в «похожие».
    metal = index.lookup("Стол обеденный", "", "шт.", "2026-10-01", params=[SearchParam(name="Материал", value="металл")])
    by_title = {o.title: o for o in metal.offers}
    assert by_title["Стол обеденный деревянный"].analog and "параметры не совпали" in by_title["Стол обеденный деревянный"].note
    # Магазины для порога автопоиска: с параметрами считаются только подтвердившие.
    ranked = index.rank("Стол обеденный", params=legs)
    assert index.matched_shops(ranked) == 2 and index.matched_shops(ranked, confirmed_only=True) == 1
    # Нигде не подтверждено — цена по всем совпавшим, с просьбой проверить.
    grey = index.lookup("Стол обеденный", "", "шт.", "2026-10-01", params=[SearchParam(name="Цвет", value="серый")])
    assert grey.price == 8500 and "заданные параметры в предложениях не подтверждены — проверьте" in grey.comment
    # Числовой параметр оператора сверяется как размеры из характеристик.
    index.set_offers(other.id, [Extracted(name="Стол обеденный 1200х800", price=12000), Extracted(name="Стол обеденный 1600х900", price=15000)], "карта сайта")
    sized = index.lookup("Стол обеденный", "", "шт.", "2026-10-01", params=[SearchParam(name="Размер", value="1200х800 мм")])
    assert sized.price == 12000 and not {o.title: o for o in sized.offers}["Стол обеденный 1200х800"].analog


def test_supplier_endpoints_and_lookup(tmp_path: Path) -> None:
    saved = (supplier_index.dir, dict(supplier_index.suppliers), dict(supplier_index.offers), internet_prices.provider)
    supplier_index.dir = tmp_path / "suppliers"
    supplier_index.suppliers.clear()
    supplier_index.offers.clear()
    supplier_index._rebuild()
    internet_prices.provider = SupplierIndexProvider(supplier_index)
    try:
        assert client.post("/api/suppliers", json={"name": "Плохой", "site": "просто текст"}).status_code == 400
        created = client.post("/api/suppliers", json={"name": "Прайсовый поставщик"})
        assert created.status_code == 200
        sid = created.json()["id"]
        assert client.post(f"/api/suppliers/{sid}/crawl").status_code == 400  # сайта нет
        assert client.post("/api/suppliers/nope/crawl").status_code == 404

        updated = client.put(f"/api/suppliers/{sid}", json={"sections": ["Мебель", " мебель", "Пищеблок"], "name": " Прайсовый  поставщик "})
        assert updated.status_code == 200 and updated.json()["sections"] == ["Мебель", "Пищеблок"] and updated.json()["name"] == "Прайсовый поставщик"

        _price_list(tmp_path / "прайс.xlsx")
        with open(tmp_path / "прайс.xlsx", "rb") as f:
            upload = client.post(f"/api/suppliers/{sid}/pricelist", files={"file": ("p.xlsx", f, "application/octet-stream")}, data={"file_name": "прайс сентябрь.xlsx", "section": "Мебель"})
        assert upload.status_code == 200 and upload.json()["offers"] == 2 and upload.json()["source"] == "прайс «Мебель» прайс сентябрь.xlsx"
        listed = client.get("/api/suppliers").json()
        assert listed["offers"] == 2 and listed["suppliers"][0]["status"] == "done"
        sample = client.get(f"/api/suppliers/{sid}/sample").json()["offers"]
        assert len(sample) == 2 and all(o["section"] == "Мебель" for o in sample)
        # Прайс другого раздела добавляется, а не затирает мебель.
        _price_list(tmp_path / "спорт.xlsx", with_header=False)
        with open(tmp_path / "спорт.xlsx", "rb") as f:
            sport = client.post(f"/api/suppliers/{sid}/pricelist", files={"file": ("s.xlsx", f, "application/octet-stream")}, data={"section": "Спорт"})
        assert sport.status_code == 200 and sport.json()["offers"] == 5 and sport.json()["sections"] == ["Мебель", "Пищеблок", "Спорт"]

        info = client.get("/api/internet").json()
        assert info["configured"] and info["provider"] == "suppliers" and "5 позиций" in info["model"]
        lookup = client.post("/api/internet/lookup", json={"items": [{"id": "r1", "name": "Стул детский регулируемый по высоте", "unit": "шт.", "section": "Мебель"}, {"id": "r2", "name": "Ножничный подъёмник"}]})
        assert lookup.status_code == 200
        lookups = lookup.json()["lookups"]
        assert lookups["r1"]["status"] == "found" and lookups["r1"]["price"] == 950 and lookups["r1"]["offers"][0]["shop"] == "Прайсовый поставщик"
        assert "раздел «Мебель»" in lookups["r1"]["offers"][0]["note"]
        assert lookups["r2"]["status"] == "not_found"
        assert not (tmp_path / "internet_prices.json").exists()  # индекс не кэшируется

        assert client.delete(f"/api/suppliers/{sid}").status_code == 204
        assert client.get("/api/suppliers").json()["suppliers"] == []
        assert client.put(f"/api/suppliers/{sid}", json={"name": "x"}).status_code == 404
    finally:
        supplier_index.dir, suppliers, offers, internet_prices.provider = saved
        supplier_index.suppliers.clear()
        supplier_index.suppliers.update(suppliers)
        supplier_index.offers.clear()
        supplier_index.offers.update(offers)
        supplier_index._rebuild()
