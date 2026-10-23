"""Автопоиск поставщиков: по позиции спецификации — веб-поиск, чтение найденных страниц по
разметке, найденные магазины — в индекс поставщиков (и в очередь на обход каталога).

Результат поиска по запросу кэшируется на ``ttl_days``: одинаковые позиции разных объектов
не гоняют поисковик заново. Маркетплейсы и не-магазины (видео, соцсети, объявления)
пропускаются: они либо закрыты для роботов, либо цен там нет.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from ...models import SearchParam
from ..attributes import parse_params
from ..params import extract_params
from ..websearch import SearchEngine, SearchHit
from .crawler import USER_AGENT
from .extract import Extracted, extract_offers

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / ".data"
SKIP_HOSTS = (
    "ozon.ru", "wildberries.ru", "market.yandex.ru", "yandex.ru", "ya.ru", "avito.ru", "aliexpress", "megamarket.ru",
    "sbermegamarket.ru", "lamoda.ru", "youtube.com", "youtu.be", "wikipedia.org", "dzen.ru", "vk.com", "ok.ru", "t.me",
    "pinterest.", "2gis.", "google.", "facebook.com", "instagram.com", "rutube.ru", "otzovik.com", "irecommend.ru",
    "yell.ru", "zoon.ru", "gosuslugi.ru", "zakupki.gov.ru", "kontur.ru", "rusprofile.ru", "list-org.com", "yandex.com",
)
SKIP_EXT = re.compile(r"\.(pdf|doc|docx|xls|xlsx|zip|rar|jpg|jpeg|png|gif|webp)$", re.I)
MAX_HITS = 8
PAGE_TIMEOUT = 10.0  # медленный магазин не должен держать позицию
PAGE_DELAY = 0.3
FETCH_WORKERS = 4  # страницы из выдачи — параллельно, они с разных сайтов
MAX_BODY = 3 * 1024 * 1024


@dataclass
class DiscoveredPage:
    url: str
    host: str
    site_name: str = ""
    offers: list[Extracted] = field(default_factory=list)


def build_query(name: str, description: str = "", extra: str = "") -> str:
    """«Стеллаж с перфорированными полками» + характеристики «…2000х1000х400(h)» →
    «Стеллаж с перфорированными полками 2000x1000x400 купить»; без параметров — просто название.
    ``extra`` — слова из параметров оператора («ножки металл»), идут сразу за названием.
    Помещение из спецификации в запрос НЕ добавляем: оно уводит выдачу в чужую отрасль
    («холодильник … комната охраны» → поставщики модульных зданий), помещение учитывает матчер."""
    text = re.sub(r"\s+", " ", name).strip()
    params = extract_params(description).describe()
    return " ".join(part for part in (text, " ".join(extra.split()), params, "купить") if part)[:200]


def host_of(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_shop_candidate(url: str) -> bool:
    host = host_of(url)
    if not host or "." not in host or SKIP_EXT.search(urlsplit(url).path or ""):
        return False
    return not any(skip in host for skip in SKIP_HOSTS)


TITLE_TAIL_NOISE = re.compile(r"\d|купить|цена|прода|магазин|официальн|производител", re.I)


def site_name_of(html: str) -> str:
    """Название магазина: og:site_name; иначе короткий хвост <title> после «|», «—», «-»,
    если он похож на имя, а не на слоган («купить … от производителя»). Иначе пусто — возьмут хост."""
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.find("meta", attrs={"property": "og:site_name"})
    if meta is not None and meta.get("content"):
        return " ".join(str(meta.get("content")).split())[:80]
    title = soup.title.get_text(" ") if soup.title else ""
    parts = [p.strip() for p in re.split(r"\s[|—–-]\s", title) if p.strip()]
    if len(parts) < 2:
        return ""
    tail = parts[-1]
    return tail if len(tail) <= 32 and not TITLE_TAIL_NOISE.search(tail) else ""


class WebPriceSearch:
    def __init__(
        self,
        engine: SearchEngine,
        index,  # SupplierIndex — без аннотации, чтобы не тянуть импорт по кругу
        data_dir: str | Path | None = None,
        ttl_days: int = 7,
        max_hits: int = MAX_HITS,
        client: httpx.Client | None = None,
        page_delay: float = PAGE_DELAY,
    ):
        self.engine = engine
        self.index = index
        self.dir = Path(data_dir or os.environ.get("DATA_DIR") or DEFAULT_DATA_DIR)
        self.path = self.dir / "web_search_cache.json"
        self.ttl_days = ttl_days
        self.max_hits = max_hits
        self.client = client or httpx.Client(timeout=httpx.Timeout(PAGE_TIMEOUT, connect=10.0), follow_redirects=True, headers={"User-Agent": USER_AGENT})
        self.page_delay = page_delay
        self._cache: dict[str, dict] = {}
        self._robots: dict[str, robotparser.RobotFileParser] = {}
        self._lock = threading.Lock()
        self._save_lock = threading.Lock()  # параллельные поиски пишут кэш по очереди
        self._fetch_lock = threading.Lock()
        self._last_fetch = 0.0

    # ---------- кэш ----------

    def load(self) -> None:
        if self.path.exists():
            with self._lock:
                self._cache = json.loads(self.path.read_text(encoding="utf-8")).get("queries", {})

    def save(self) -> None:
        with self._save_lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            with self._lock:
                payload = json.dumps({"queries": self._cache}, ensure_ascii=False)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(self.path)

    @property
    def cached_queries(self) -> int:
        with self._lock:
            return len(self._cache)

    def _fresh(self, query: str, today: str) -> list[DiscoveredPage] | None:
        with self._lock:
            entry = self._cache.get(query)
        if not entry:
            return None
        try:
            age = (date.fromisoformat(today) - date.fromisoformat(entry.get("searched_at", ""))).days
        except ValueError:
            return None
        if not 0 <= age < self.ttl_days:
            return None
        return [
            DiscoveredPage(url=p["url"], host=p["host"], site_name=p.get("site_name", ""), offers=[Extracted(**o) for o in p.get("offers", [])])
            for p in entry.get("pages", [])
        ]

    # ---------- поиск ----------

    def find(self, name: str, description: str, unit: str, today: str, params: Iterable[SearchParam] = (),
             enough: Callable[[], bool] | None = None) -> list[DiscoveredPage]:
        """Страницы магазинов с предложениями по позиции; найденное сразу уходит в индекс.
        Лестница запросов: название (+объём, если есть) → только название → с характеристиками.
        Каждый вариант пробуется, его предложения добавляются в индекс, и если задан ``enough`` —
        перебор идёт, пока он не вернёт True (т.е. в индексе появился ПОДХОДЯЩИЙ товар, прошедший
        матчер), а не до первой любой страницы: иначе мусорная рубрика оборвала бы лестницу. Без
        ``enough`` (поиск по модели/истории) останавливаемся на первой странице с предложениями."""
        manual = parse_params(params)
        hint = extract_params(description).search_hint()  # ходовой параметр: объём/диаметр/мощность (не габариты)
        queries: list[str] = []
        for query in (
            build_query(name, "", f"{manual.query()} {hint}".strip()),  # как ищет человек: название + объём (если есть)
            build_query(name, "", manual.query()),  # просто название
            build_query(name, f"{description} {manual.numeric_text}", manual.query()),  # + все характеристики (габариты)
            build_query(name, manual.numeric_text, manual.query()),
            build_query(name),
        ):
            if query not in queries:
                queries.append(query)
        pages: list[DiscoveredPage] = []
        for query in queries:
            pages = self._search(query, today)
            found = [page for page in pages if page.offers]
            for page in found:
                self.index.discover(page.host, page.site_name, query, page.offers)
            if found and (enough is None or enough()):
                break  # подходящий товар найден (или не задан критерий) — дальше не перебираем
        return pages

    def _search(self, query: str, today: str) -> list[DiscoveredPage]:
        pages = self._fresh(query, today)
        if pages is not None:
            return pages
        hits = self.engine.search(query, max_results=self.max_hits * 3)
        pages = self._read_pages(hits)
        with self._lock:
            self._cache[query] = {
                "searched_at": today,
                "pages": [{"url": p.url, "host": p.host, "site_name": p.site_name, "offers": [o.__dict__ for o in p.offers]} for p in pages],
            }
        self.save()
        return pages

    def _read_pages(self, hits: list[SearchHit]) -> list[DiscoveredPage]:
        """Страницы из выдачи читаются параллельно (это разные сайты): иначе позиция ждёт
        каждую страницу и каждый robots.txt по очереди, и один медленный сайт тянет всё."""
        candidates: list[SearchHit] = []
        seen_hosts: dict[str, int] = {}
        for hit in hits:
            if len(candidates) >= self.max_hits:
                break
            if not is_shop_candidate(hit.url):
                continue
            host = host_of(hit.url)
            if seen_hosts.get(host, 0) >= 2:  # не больше двух страниц с одного сайта
                continue
            seen_hosts[host] = seen_hosts.get(host, 0) + 1
            candidates.append(hit)
        with ThreadPoolExecutor(max_workers=min(FETCH_WORKERS, max(1, len(candidates)))) as pool:
            results = list(pool.map(self._read_page, candidates))
        return [page for page in results if page is not None]

    def _read_page(self, hit: SearchHit) -> DiscoveredPage | None:
        if not self._allowed(hit.url):
            return None
        response = self._get(hit.url)
        if response is None or "html" not in response.headers.get("content-type", "html"):
            return None
        offers = extract_offers(response.text, str(response.url))
        return DiscoveredPage(url=str(response.url), host=host_of(hit.url), site_name=site_name_of(response.text), offers=offers)

    # ---------- сеть ----------

    def _get(self, url: str) -> httpx.Response | None:
        with self._fetch_lock:
            wait = self.page_delay - (time.monotonic() - self._last_fetch)
            if wait > 0:
                time.sleep(wait)
            self._last_fetch = time.monotonic()
        try:
            response = self.client.get(url)
        except httpx.HTTPError:
            return None
        if response.status_code != 200 or len(response.content) > MAX_BODY:
            return None
        return response

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            parser = self._robots.get(base)
        if parser is None:
            parser = robotparser.RobotFileParser()
            response = self._get(base + "/robots.txt")
            parser.parse(response.text.splitlines() if response is not None else [])
            with self._lock:
                self._robots[base] = parser
        try:
            return parser.can_fetch(USER_AGENT, url) and parser.can_fetch("*", url)
        except Exception:  # noqa: BLE001
            return True
