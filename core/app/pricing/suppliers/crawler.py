"""Обход сайта поставщика: фид YML → карта сайта → переходы по ссылкам; с каждой страницы —
предложения через разметку.

Вежливость: robots.txt уважаем, не чаще двух запросов в секунду на сайт, страниц не больше
лимита, свой User-Agent. Работа долгая (минуты и часы), поэтому вызывающий код даёт
колбэки прогресса и остановки.
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable
from urllib import robotparser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from .extract import Extracted, extract_offers, is_yml, parse_sitemap, parse_yml

USER_AGENT = "DomeoSpecBot/0.1 (market price check; +https://testdesign.domeohome.ru/spec/)"  # заголовок — только ASCII
YML_CANDIDATES = ("/yml.xml", "/yandex.yml", "/yandex.xml", "/marketplace.xml", "/export/yml.xml", "/yml/yandex.xml", "/feed/yml.xml", "/upload/yml.xml")
SITEMAP_CANDIDATES = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml", "/sitemap.xml.gz")
MAX_SITEMAPS = 60
MAX_SITEMAP_URLS = 40_000
MAX_BODY = 3 * 1024 * 1024
NO_PRICE_PAGE_LIMIT = 60  # столько страниц без единой цены — на сайте нет разметки, дальше не тратим лимит
PRODUCT_HINT = re.compile(r"/(product|products|tovar|tovary|item|items|goods|catalog|katalog|shop|magazin)/", re.I)
SKIP_HINT = re.compile(r"/(news|novosti|blog|articles|stati|about|contacts|kontakty|delivery|dostavka|oplata|payment|policy|privacy|search|login|cart|basket|compare|wishlist|auth|personal)/|\.(jpg|jpeg|png|gif|webp|svg|pdf|zip|rar|doc|docx|xls|xlsx|css|js)$", re.I)


@dataclass
class CrawlResult:
    offers: list[Extracted] = field(default_factory=list)
    pages: int = 0
    source: str = ""
    error: str = ""


def normalize_site(site: str) -> str:
    site = site.strip()
    if not site:
        raise ValueError("не указан адрес сайта")
    if "://" not in site:
        site = "https://" + site
    parts = urlsplit(site)
    if not parts.netloc or "." not in parts.netloc:
        raise ValueError("адрес сайта должен быть вида https://example.ru")
    return urlunsplit((parts.scheme, parts.netloc.lower(), "", "", ""))


class SiteCrawler:
    def __init__(
        self,
        client: httpx.Client | None = None,
        delay: float = 0.5,
        max_pages: int = 3000,
        progress: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ):
        self.client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=True, headers={"User-Agent": USER_AGENT})
        self.delay = delay
        self.max_pages = max(1, max_pages)
        self.progress = progress or (lambda _: None)
        self.should_stop = should_stop or (lambda: False)
        self._last_request = 0.0

    # ---------- сеть ----------

    def _get(self, url: str) -> httpx.Response | None:
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
        try:
            response = self.client.get(url)
        except httpx.HTTPError:
            return None
        if response.status_code != 200 or len(response.content) > MAX_BODY:
            return None
        return response

    # ---------- обход ----------

    def crawl(self, site: str) -> CrawlResult:
        base = normalize_site(site)
        host = urlsplit(base).netloc
        robots = self._robots(base)

        feed = self._find_yml(base, robots)
        if feed is not None:
            url, offers = feed
            return CrawlResult(offers=offers, pages=1, source=f"фид YML {url}")

        urls, sitemap_source = self._sitemap_urls(base, robots)
        if urls:
            offers, pages = self._fetch_pages(urls, robots)
            return CrawlResult(offers=offers, pages=pages, source=f"карта сайта {sitemap_source}")

        offers, pages = self._spider(base, host, robots)
        if pages == 0:
            return CrawlResult(error="сайт не отвечает или закрыт для обхода")
        return CrawlResult(offers=offers, pages=pages, source="переходы по ссылкам")

    def _robots(self, base: str) -> robotparser.RobotFileParser:
        parser = robotparser.RobotFileParser()
        response = self._get(base + "/robots.txt")
        if response is None:
            parser.parse([])
            return parser
        parser.parse(response.text.splitlines())
        return parser

    def _allowed(self, robots: robotparser.RobotFileParser, url: str) -> bool:
        try:
            return robots.can_fetch(USER_AGENT, url) and robots.can_fetch("*", url)
        except Exception:  # noqa: BLE001 — кривой robots.txt не должен останавливать обход
            return True

    def _find_yml(self, base: str, robots: robotparser.RobotFileParser) -> tuple[str, list[Extracted]] | None:
        candidates = [base + path for path in YML_CANDIDATES]
        candidates += [s for s in (robots.site_maps() or []) if re.search(r"yml|yandex", s, re.I)]
        for url in candidates:
            if self.should_stop():
                return None
            response = self._get(url)
            if response is None or not is_yml(response.content):
                continue
            try:
                offers = parse_yml(response.content)
            except Exception:  # noqa: BLE001
                continue
            if offers:
                return url, offers
        return None

    def _sitemap_urls(self, base: str, robots: robotparser.RobotFileParser) -> tuple[list[str], str]:
        queue: deque[str] = deque(list(robots.site_maps() or []) + [base + path for path in SITEMAP_CANDIDATES])
        seen_maps: set[str] = set()
        urls: list[str] = []
        source = ""
        while queue and len(seen_maps) < MAX_SITEMAPS and len(urls) < MAX_SITEMAP_URLS:
            if self.should_stop():
                break
            map_url = queue.popleft()
            if map_url in seen_maps:
                continue
            seen_maps.add(map_url)
            response = self._get(map_url)
            if response is None:
                continue
            kind, locs = parse_sitemap(response.content)
            if kind == "index":
                queue.extend(locs)
                source = source or map_url
            elif kind == "urls":
                urls.extend(locs)
                source = source or map_url
            if not source:
                continue
        host = urlsplit(base).netloc
        same_host = [u for u in urls if urlsplit(u).netloc.lower() == host and not SKIP_HINT.search(u)]
        # Похожие на карточки товаров — вперёд, чтобы лимит страниц уходил на них.
        same_host.sort(key=lambda u: 0 if PRODUCT_HINT.search(u) else 1)
        return list(dict.fromkeys(same_host)), source

    def _fetch_pages(self, urls: list[str], robots: robotparser.RobotFileParser) -> tuple[list[Extracted], int]:
        offers: list[Extracted] = []
        pages = 0
        total = min(len(urls), self.max_pages)
        for url in urls[: self.max_pages]:
            if self.should_stop():
                break
            if not self._allowed(robots, url):
                continue
            response = self._get(url)
            pages += 1
            if response is not None and "html" in response.headers.get("content-type", "html"):
                offers.extend(extract_offers(response.text, str(response.url)))
            if pages % 20 == 0:
                self.progress(f"страниц {pages} из {total}, цен {len(offers)}")
            if pages >= NO_PRICE_PAGE_LIMIT and not offers:
                break
        self.progress(f"страниц {pages} из {total}, цен {len(offers)}")
        return offers, pages

    def _spider(self, base: str, host: str, robots: robotparser.RobotFileParser) -> tuple[list[Extracted], int]:
        queue: deque[str] = deque([base + "/"])
        seen: set[str] = {base + "/", base}
        offers: list[Extracted] = []
        pages = 0
        while queue and pages < self.max_pages:
            if self.should_stop():
                break
            url = queue.popleft()
            if not self._allowed(robots, url):
                continue
            response = self._get(url)
            if response is None:
                continue
            pages += 1
            if "html" not in response.headers.get("content-type", "html"):
                continue
            offers.extend(extract_offers(response.text, str(response.url)))
            soup = BeautifulSoup(response.text, "html.parser")
            for link in soup.find_all("a", href=True):
                target = urljoin(str(response.url), link["href"]).split("#")[0]
                parts = urlsplit(target)
                if parts.netloc.lower() != host or SKIP_HINT.search(target) or target in seen:
                    continue
                seen.add(target)
                if PRODUCT_HINT.search(target):
                    queue.appendleft(target)
                else:
                    queue.append(target)
            if pages % 20 == 0:
                self.progress(f"страниц {pages}, цен {len(offers)}")
            if pages >= NO_PRICE_PAGE_LIMIT and not offers:
                break
        self.progress(f"страниц {pages}, цен {len(offers)}")
        return offers, pages
