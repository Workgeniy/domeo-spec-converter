"""Картинка товара из интернета: миниатюра со страницы предложения как запасной источник."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from app.images import fetch_product_image, image_url_from_html, thumbnail_data_uri
from app.models import InternetLookup, InternetOffer, MatchRequestItem
from app.pricing.internet import InternetPriceService, best_offer_url


def _png(color: tuple[int, int, int] = (200, 120, 40), size: tuple[int, int] = (600, 400)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class _Provider:
    """Подставной поиск: всегда находит, с одной точной ссылкой и одним аналогом."""

    name = "fake"
    model = "fake-model"

    def lookup(self, name, description, unit, today, section="", params=(), type_mark="") -> InternetLookup:
        offers = [
            InternetOffer(title=f"{name}", url="https://shop.example/product", shop="Магазин", price=1200),
            InternetOffer(title="аналог", url="https://shop.example/other", shop="Другой", price=1500, analog=True),
        ]
        return InternetLookup(status="found", query=name, looked_up_at=today, offers=offers, price=1200, provider=self.name)


def test_thumbnail_data_uri_makes_jpeg() -> None:
    uri = thumbnail_data_uri(_png(size=(800, 800)))
    assert uri.startswith("data:image/jpeg;base64,")
    import base64

    payload = base64.b64decode(uri.split(",", 1)[1])
    im = Image.open(io.BytesIO(payload))
    assert max(im.size) <= 240  # уменьшено до миниатюры
    assert thumbnail_data_uri("не картинка".encode("utf-8")) == ""  # мусор не роняет


def test_image_url_from_html_prefers_opengraph() -> None:
    html = '<html><head><meta property="og:image" content="/img/p.jpg"><title>t</title></head></html>'
    assert image_url_from_html(html, "https://shop.example/product") == "https://shop.example/img/p.jpg"
    # JSON-LD, если og нет
    ld = '<html><head><script type="application/ld+json">{"@type":"Product","image":["https://cdn.example/a.jpg"]}</script></head></html>'
    assert image_url_from_html(ld, "https://shop.example/p") == "https://cdn.example/a.jpg"
    assert image_url_from_html("<html></html>", "https://shop.example/p") == ""


def test_fetch_product_image_follows_page_then_image() -> None:
    png = _png()

    def fake_get(url: str) -> tuple[int, bytes, str]:
        if url == "https://shop.example/product":
            return 200, b'<meta property="og:image" content="https://cdn.example/p.jpg">', "text/html; charset=utf-8"
        if url == "https://cdn.example/p.jpg":
            return 200, png, "image/jpeg"
        return 404, b"", ""

    uri = fetch_product_image("https://shop.example/product", get=fake_get)
    assert uri.startswith("data:image/jpeg;base64,")
    # Сеть упала / не картинка / не http — пусто, без исключений.
    assert fetch_product_image("https://shop.example/product", get=lambda u: (500, b"", "")) == ""
    assert fetch_product_image("ftp://x/y", get=fake_get) == ""


def test_best_offer_url_prefers_exact_at_recommended_price() -> None:
    lookup = InternetLookup(
        status="found",
        price=1200,
        offers=[
            InternetOffer(url="https://a", price=1500, analog=True),
            InternetOffer(url="https://b", price=1200),
        ],
    )
    assert best_offer_url(lookup) == "https://b"
    assert best_offer_url(InternetLookup(status="found", offers=[])) == ""


def test_service_attaches_image_only_when_requested(tmp_path: Path) -> None:
    seen: list[str] = []

    def fetcher(url: str) -> str:
        seen.append(url)
        return "data:image/jpeg;base64,AAAA" if url == "https://shop.example/product" else ""

    service = InternetPriceService(_Provider(), data_dir=tmp_path, image_fetcher=fetcher)
    # Позиция без своей картинки → просим из интернета, берётся со страницы точного предложения.
    with_img = service.lookup_many([MatchRequestItem(id="a", name="Стул детский", want_image=True)])["a"]
    assert with_img.image == "data:image/jpeg;base64,AAAA"
    assert seen == ["https://shop.example/product"]  # тянули именно точное предложение, не аналог
    # Позиция со своей картинкой из файла (want_image не выставлен) → в интернет за картинкой не ходим.
    without = service.lookup_many([MatchRequestItem(id="b", name="Табурет")], refresh=True)["b"]
    assert without.image == "" and seen == ["https://shop.example/product"]


def test_service_image_disabled_by_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("INTERNET_PRICE_IMAGES", "0")
    service = InternetPriceService(_Provider(), data_dir=tmp_path, image_fetcher=lambda url: "data:image/jpeg;base64,ZZZZ")
    lookup = service.lookup_many([MatchRequestItem(id="a", name="Стул", want_image=True)])["a"]
    assert lookup.image == ""  # выключено переменной окружения
