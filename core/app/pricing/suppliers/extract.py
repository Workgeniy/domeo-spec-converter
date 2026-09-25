"""Извлечение предложений (название, цена, артикул, ссылка) из страниц магазинов и фидов.

Порядок — от надёжного к эвристике: разметка schema.org в JSON-LD, микроразметка itemprop,
OpenGraph (product:price:amount), и только потом «заголовок h1 + первая цена на странице».
Фиды YML (формат Яндекс Маркета) и карты сайта разбираются отдельно.
"""

from __future__ import annotations

import gzip
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

PRICE_RE = re.compile(r"(\d[\d\s  ]*(?:[.,]\d{1,2})?)")
RUB_HINT = re.compile(r"₽|руб|р\.|rub", re.I)
ACCEPTED_CURRENCIES = {None, "", "RUB", "RUR", "₽", "руб", "руб."}
MIN_PRICE, MAX_PRICE = 1.0, 100_000_000.0


@dataclass
class Extracted:
    name: str
    price: float
    url: str = ""
    sku: str = ""
    source: str = ""  # jsonld | microdata | og | heuristic | yml | xlsx


def parse_price(value: Any) -> float | None:
    """«12 345,60 ₽» → 12345.6; мусор и неправдоподобные суммы → None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        price = float(value)
    else:
        text = str(value).replace(" ", " ").replace(" ", " ").strip()
        match = PRICE_RE.search(text)
        if not match:
            return None
        number = match.group(1).replace(" ", "")
        if number.count(",") == 1 and "." not in number:
            number = number.replace(",", ".")
        elif "," in number and "." in number:
            number = number.replace(",", "")
        try:
            price = float(number)
        except ValueError:
            return None
    return price if MIN_PRICE <= price <= MAX_PRICE else None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return _text(value.get("name") or value.get("@value") or "")
    if isinstance(value, list):
        return _text(value[0]) if value else ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _currency_ok(value: Any) -> bool:
    return _text(value) in ACCEPTED_CURRENCIES


def _dedupe(offers: Iterable[Extracted]) -> list[Extracted]:
    seen: set[tuple[str, float]] = set()
    result: list[Extracted] = []
    for offer in offers:
        key = (offer.name.lower(), offer.price)
        if offer.name and key not in seen:
            seen.add(key)
            result.append(offer)
    return result


# ---------- JSON-LD ----------


def _walk(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _is_product(node: dict[str, Any]) -> bool:
    types = node.get("@type")
    if isinstance(types, str):
        types = [types]
    return isinstance(types, list) and any(str(t).endswith("Product") for t in types)


def _offer_price(offer: Any) -> float | None:
    if not isinstance(offer, dict):
        return None
    if not _currency_ok(offer.get("priceCurrency")):
        return None
    for key in ("price", "lowPrice"):
        price = parse_price(offer.get(key))
        if price is not None:
            return price
    spec = offer.get("priceSpecification")
    if isinstance(spec, list):
        spec = spec[0] if spec else None
    if isinstance(spec, dict):
        return parse_price(spec.get("price"))
    return None


def _from_jsonld(soup: BeautifulSoup, page_url: str) -> list[Extracted]:
    offers: list[Extracted] = []
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            # Иногда в одном теге несколько объектов подряд или мусор в конце.
            try:
                data = json.loads(raw.strip().rstrip(";"))
            except json.JSONDecodeError:
                continue
        for node in _walk(data):
            if not _is_product(node):
                continue
            name = _text(node.get("name"))
            if not name:
                continue
            raw_offers = node.get("offers")
            candidates = raw_offers if isinstance(raw_offers, list) else [raw_offers]
            for offer in candidates:
                price = _offer_price(offer)
                if price is None:
                    continue
                url = _text(offer.get("url")) or _text(node.get("url")) or page_url
                sku = _text(node.get("sku") or node.get("mpn") or node.get("productID"))
                offers.append(Extracted(name=name, price=price, url=url, sku=sku, source="jsonld"))
                break  # одна цена на товар
    return offers


# ---------- микроразметка ----------


def _prop(scope: Any, prop: str) -> str:
    node = scope.find(attrs={"itemprop": prop})
    if node is None:
        return ""
    for attr in ("content", "value"):
        if node.get(attr):
            return _text(node.get(attr))
    if node.name == "meta":
        return ""
    return _text(node.get_text(" "))


def _from_microdata(soup: BeautifulSoup, page_url: str) -> list[Extracted]:
    offers: list[Extracted] = []
    for scope in soup.find_all(attrs={"itemtype": re.compile("schema.org/Product", re.I)}):
        name = _prop(scope, "name")
        price = parse_price(_prop(scope, "price") or _prop(scope, "lowPrice"))
        if not name or price is None or not _currency_ok(_prop(scope, "priceCurrency")):
            continue
        url_node = scope.find(attrs={"itemprop": "url"})
        url = _text(url_node.get("href") or url_node.get("content")) if url_node else ""
        offers.append(Extracted(name=name, price=price, url=url or page_url, sku=_prop(scope, "sku"), source="microdata"))
    return offers


# ---------- OpenGraph ----------


def _meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        node = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if node is not None and node.get("content"):
            return _text(node.get("content"))
    return ""


def _from_opengraph(soup: BeautifulSoup, page_url: str) -> list[Extracted]:
    price = parse_price(_meta(soup, "product:price:amount", "og:price:amount"))
    if price is None or not _currency_ok(_meta(soup, "product:price:currency", "og:price:currency")):
        return []
    name = _meta(soup, "og:title")
    if not name:
        return []
    return [Extracted(name=name, price=price, url=_meta(soup, "og:url") or page_url, source="og")]


# ---------- эвристика: h1 + цена ----------


MAX_PRICE_NODES_FOR_CARD = 3  # больше — это листинг категории, и «h1 + первая цена» даст мусор


def _from_heuristic(soup: BeautifulSoup, page_url: str) -> list[Extracted]:
    headings = soup.find_all("h1")
    if len(headings) != 1:
        return []
    name = _text(headings[0].get_text(" "))
    if not name:
        return []
    priced: list[float] = []
    for node in soup.select('[itemprop="price"], [class*="price" i], [id*="price" i]'):
        text = node.get("content") or node.get_text(" ")
        if not text or not RUB_HINT.search(text) and node.name != "meta":
            continue
        price = parse_price(text)
        if price is not None:
            priced.append(price)
            if len(priced) > MAX_PRICE_NODES_FOR_CARD:
                return []  # страница категории: цен много, к какой относится h1 — неизвестно
    if not priced:
        return []
    return [Extracted(name=name, price=priced[0], url=page_url, source="heuristic")]


def _absolute(offers: list[Extracted], page_url: str) -> list[Extracted]:
    for offer in offers:
        if offer.url and not offer.url.startswith(("http://", "https://")):
            offer.url = urljoin(page_url, offer.url)
    return offers


def extract_offers(html: str, page_url: str) -> list[Extracted]:
    """Все предложения со страницы (карточка — одно, листинг с разметкой — несколько)."""
    soup = BeautifulSoup(html, "html.parser")
    for extractor in (_from_jsonld, _from_microdata, _from_opengraph, _from_heuristic):
        offers = _dedupe(extractor(soup, page_url))
        if offers:
            return _absolute(offers, page_url)
    return []


# ---------- YML (Яндекс Маркет) и карты сайта ----------


def maybe_gunzip(content: bytes) -> bytes:
    return gzip.decompress(content) if content[:2] == b"\x1f\x8b" else content


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def is_yml(content: bytes) -> bool:
    head = maybe_gunzip(content)[:4000].lower()
    return b"<yml_catalog" in head


def parse_yml(content: bytes) -> list[Extracted]:
    root = ET.fromstring(maybe_gunzip(content))
    offers: list[Extracted] = []
    for offer in root.iter():
        if _local(offer.tag) != "offer":
            continue
        fields = {_local(child.tag): (child.text or "").strip() for child in offer}
        name = fields.get("name") or " ".join(p for p in (fields.get("vendor", ""), fields.get("model", "")) if p).strip()
        price = parse_price(fields.get("price"))
        if not name or price is None or not _currency_ok(fields.get("currencyid")):
            continue
        offers.append(Extracted(name=name, price=price, url=fields.get("url", ""), sku=fields.get("vendorcode", ""), source="yml"))
    return _dedupe(offers)


def parse_sitemap(content: bytes) -> tuple[str, list[str]]:
    """('index', [адреса вложенных карт]) или ('urls', [адреса страниц]); ('', []) — не карта."""
    try:
        root = ET.fromstring(maybe_gunzip(content))
    except ET.ParseError:
        return "", []
    kind = _local(root.tag)
    if kind not in ("sitemapindex", "urlset"):
        return "", []
    locs = [(node.text or "").strip() for node in root.iter() if _local(node.tag) == "loc"]
    return ("index" if kind == "sitemapindex" else "urls"), [loc for loc in locs if loc]
