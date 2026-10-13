"""Миниатюры товаров для приложения и КП.

Одна и та же компактная картинка (JPEG ≤240px как data-URI) делается и из встроенной в
xlsx картинки, и со страницы товара в интернете. Сеть и декодирование обёрнуты так, что
любая неудача возвращает пустую строку, а не роняет разбор или поиск цены.
"""

from __future__ import annotations

import base64
import io
import json
import re
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlsplit

THUMB_PX = 240  # миниатюра: хватает и на карточку в приложении, и на вставку в КП
MAX_PAGE_BYTES = 3 * 1024 * 1024  # крупнее — не карточка товара, не тратим время
MAX_IMAGE_BYTES = 8 * 1024 * 1024
USER_AGENT = "DomeoSpecBot/0.1 (product image; +https://testdesign.domeohome.ru/spec/)"  # только ASCII

# url -> (статус, тело, content-type); вынесено, чтобы в тестах подменять сеть.
HttpGet = Callable[[str], "tuple[int, bytes, str]"]


def thumbnail_data_uri(data: bytes) -> str:
    """Байты картинки → миниатюра JPEG ≤THUMB_PX как data-URI; при любой ошибке — ''."""
    try:
        from PIL import Image  # Pillow в зависимостях; без него — просто без картинок

        im = Image.open(io.BytesIO(data))
        im.thumbnail((THUMB_PX, THUMB_PX))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=75)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 — картинки не критичны
        return ""


def _jsonld_image(node: Any) -> str:
    """Поле image из объекта Product разметки JSON-LD (строка / объект / список)."""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        return str(node.get("url") or node.get("contentUrl") or "")
    if isinstance(node, list) and node:
        return _jsonld_image(node[0])
    return ""


def _jsonld_images(soup) -> Iterable[str]:
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                types = cur.get("@type")
                types = [types] if isinstance(types, str) else (types or [])
                if any(str(t).endswith("Product") for t in types) and cur.get("image"):
                    yield _jsonld_image(cur.get("image"))
                stack.extend(cur.values())
            elif isinstance(cur, list):
                stack.extend(cur)


def image_url_from_html(html: str, page_url: str) -> str:
    """Главная картинка товара со страницы: og:image/twitter:image, затем image из JSON-LD
    Product, затем link rel=image_src. '' — ничего подходящего не нашли."""
    try:
        from bs4 import BeautifulSoup
    except Exception:  # noqa: BLE001
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for prop in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src"):
        node = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        content = (node.get("content") if node else "") or ""
        if content.strip():
            return urljoin(page_url, content.strip())
    for img in _jsonld_images(soup):
        if img and img.strip():
            return urljoin(page_url, img.strip())
    link = soup.find("link", attrs={"rel": re.compile("image_src", re.I)})
    if link and link.get("href"):
        return urljoin(page_url, link["href"].strip())
    return ""


def _default_get(url: str) -> tuple[int, bytes, str]:
    import httpx

    with httpx.Client(
        timeout=httpx.Timeout(10.0, connect=6.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        response = client.get(url)
        return response.status_code, response.content, response.headers.get("content-type", "")


def _usable(url: str) -> bool:
    return url.startswith(("http://", "https://")) and not urlsplit(url).path.lower().endswith(".svg")


def fetch_product_image(page_url: str, *, get: HttpGet | None = None) -> str:
    """Миниатюра товара со страницы предложения: находим главную картинку (og:image и т. п.),
    скачиваем, уменьшаем. Любая сетевая или прочая неудача → '' (поиск цены это не роняет)."""
    if not _usable(page_url):
        return ""
    fetch = get or _default_get
    try:
        status, body, ctype = fetch(page_url)
    except Exception:  # noqa: BLE001 — сеть не должна ронять поиск
        return ""
    if status != 200 or not body or len(body) > MAX_PAGE_BYTES:
        return ""
    if ctype.lower().startswith("image/"):  # ссылка оффера указывает сразу на картинку
        return thumbnail_data_uri(body)
    img_url = image_url_from_html(body.decode("utf-8", "replace"), page_url)
    if not _usable(img_url):
        return ""
    try:
        status, body, ctype = fetch(img_url)
    except Exception:  # noqa: BLE001
        return ""
    if status != 200 or not body or len(body) > MAX_IMAGE_BYTES:
        return ""
    if ctype and not ctype.lower().startswith("image/"):
        return ""
    return thumbnail_data_uri(body)
