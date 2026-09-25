"""Индекс цен поставщиков: список поставщиков, их предложения на диске, обход сайтов в фоне
и поиск по индексу для позиций спецификации (в той же форме, что и поиск в интернете).

Хранение: ``DATA_DIR/suppliers/index.json`` (поставщики, настройки) и ``offers/<id>.json``
(их предложения). Обход по кнопке — отдельный поток на поставщика; сайты, найденные
автопоиском, встают в очередь и обходятся одним фоновым потоком по одному.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import tempfile
import threading
import uuid
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ...models import InternetLookup, InternetOffer, Supplier, SupplierIndexInfo, SupplierOffer
from ..history import normalize_name, tokens
from .crawler import SiteCrawler, normalize_site
from .extract import Extracted
from .xlsx_import import read_price_list

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / ".data"
MOSCOW = ZoneInfo("Europe/Moscow")
MATCH_THRESHOLD = 0.6  # с этой оценки считаем, что предложение — та же позиция
ANALOG_THRESHOLD = 0.45  # ниже — не показываем даже как похожее (одно общее слово из трёх — ещё не похоже)
OFFERS_SHOWN = 6
DEFAULT_AUTOCRAWL_PAGES = 300
DEFAULT_MIN_SHOPS = 3  # столько разных магазинов по позиции считаем «картиной рынка»


def _today() -> str:
    return datetime.now(MOSCOW).date().isoformat()


def _host(site: str) -> str:
    host = urlsplit(site).netloc.lower() if "://" in site else site.lower()
    return host[4:] if host.startswith("www.") else host


class OfferMatcher:
    """Индекс слово → предложения; оценка та же, что у сопоставления с историей."""

    def __init__(self, offers: list[SupplierOffer] | None = None):
        self.offers: list[SupplierOffer] = []
        self.index: dict[str, set[int]] = defaultdict(set)
        self.offer_tokens: list[set[str]] = []
        self.offer_keys: list[str] = []
        self.add(offers or [])

    def add(self, offers: list[SupplierOffer]) -> None:
        for offer in offers:
            i = len(self.offers)
            self.offers.append(offer)
            toks = tokens(offer.name)
            self.offer_tokens.append(toks)
            self.offer_keys.append(normalize_name(offer.name))
            for t in toks:
                self.index[t].add(i)

    def search(self, name: str) -> list[tuple[SupplierOffer, float]]:
        key = normalize_name(name)
        query = tokens(name)
        if not query:
            return []
        scored: dict[int, float] = {}
        for t in query:
            for i in self.index.get(t, ()):
                if i not in scored:
                    scored[i] = self._score(key, query, i)
        return sorted(((self.offers[i], s) for i, s in scored.items() if s >= ANALOG_THRESHOLD), key=lambda pair: (-pair[1], pair[0].price))

    def _score(self, key: str, query: set[str], i: int) -> float:
        candidate = self.offer_tokens[i]
        if not candidate:
            return 0.0
        common = len(query & candidate)
        score = 0.65 * common / len(query) + 0.35 * common / len(candidate)
        if self.offer_keys[i] == key:
            return 1.0
        if self.offer_keys[i].startswith(key[:20]) or key.startswith(self.offer_keys[i][:20]):
            score = min(1.0, score + 0.15)
        return round(score, 3)


class SupplierIndex:
    def __init__(self, data_dir: str | Path | None = None):
        self.dir = Path(data_dir or os.environ.get("DATA_DIR") or DEFAULT_DATA_DIR) / "suppliers"
        self.suppliers: dict[str, Supplier] = {}
        self.offers: dict[str, list[SupplierOffer]] = {}
        self.updated_at = ""
        self.autocrawl_pages = DEFAULT_AUTOCRAWL_PAGES
        self.min_shops = DEFAULT_MIN_SHOPS
        self.search_engine = ""  # название движка автопоиска — для сводки
        self._matcher = OfferMatcher()
        self._lock = threading.RLock()
        self._save_lock = threading.Lock()  # запись файлов — по одному потоку, иначе гонка за index.tmp
        self._jobs: dict[str, threading.Thread] = {}
        self._stop: set[str] = set()
        self._queue: deque[str] = deque()
        self._worker: threading.Thread | None = None
        self._crawler_factory = None  # для тестов: подменить SiteCrawler

    # ---------- хранение ----------

    def load(self) -> None:
        index_file = self.dir / "index.json"
        if not index_file.exists():
            return
        raw = json.loads(index_file.read_text(encoding="utf-8"))
        with self._lock:
            self.updated_at = raw.get("updated_at", "")
            self.autocrawl_pages = int(raw.get("autocrawl_pages", DEFAULT_AUTOCRAWL_PAGES))
            self.min_shops = int(raw.get("min_shops", DEFAULT_MIN_SHOPS))
            for item in raw.get("suppliers", []):
                supplier = Supplier.model_validate(item)
                if supplier.status == "running":  # обход прервался перезапуском сервиса
                    supplier.status = "error"
                    supplier.error = "обход прерван перезапуском сервиса"
                    supplier.progress = ""
                self.suppliers[supplier.id] = supplier
                offers_file = self.dir / "offers" / f"{supplier.id}.json"
                if offers_file.exists():
                    self.offers[supplier.id] = [SupplierOffer.model_validate(o) for o in json.loads(offers_file.read_text(encoding="utf-8"))]
            self._rebuild()

    def save(self) -> None:
        with self._save_lock:
            (self.dir / "offers").mkdir(parents=True, exist_ok=True)
            with self._lock:
                payload = {
                    "updated_at": self.updated_at,
                    "autocrawl_pages": self.autocrawl_pages,
                    "min_shops": self.min_shops,
                    "suppliers": [s.model_dump() for s in self.suppliers.values()],
                }
                snapshot = {sid: [o.model_dump() for o in offers] for sid, offers in self.offers.items()}
            _write_json(self.dir / "index.json", payload)
            for sid, offers in snapshot.items():
                _write_json(self.dir / "offers" / f"{sid}.json", offers)

    # ---------- поставщики ----------

    def info(self) -> SupplierIndexInfo:
        with self._lock:
            suppliers = sorted(self.suppliers.values(), key=lambda s: (s.discovered, s.name.lower()))
            return SupplierIndexInfo(
                suppliers=[s.model_copy() for s in suppliers],
                offers=sum(len(o) for o in self.offers.values()),
                updated_at=self.updated_at,
                autocrawl_pages=self.autocrawl_pages,
                min_shops=self.min_shops,
                queued=len(self._queue),
                search_engine=self.search_engine,
            )

    def set_settings(self, autocrawl_pages: int | None = None, min_shops: int | None = None) -> SupplierIndexInfo:
        with self._lock:
            if autocrawl_pages is not None:
                self.autocrawl_pages = max(0, min(int(autocrawl_pages), 50_000))
            if min_shops is not None:
                self.min_shops = max(1, min(int(min_shops), 10))
        self.save()
        return self.info()

    def add(self, name: str, site: str = "", max_pages: int = 3000) -> Supplier:
        name = " ".join(name.split())
        if not name:
            raise ValueError("не указано название поставщика")
        site = normalize_site(site) if site.strip() else ""
        supplier = Supplier(id=uuid.uuid4().hex[:8], name=name, site=site, kind="site" if site else "pricelist", max_pages=max(50, min(max_pages, 50_000)))
        with self._lock:
            self.suppliers[supplier.id] = supplier
        self.save()
        return supplier

    def remove(self, supplier_id: str) -> None:
        self.stop_crawl(supplier_id)
        with self._lock:
            if supplier_id not in self.suppliers:
                raise KeyError(supplier_id)
            del self.suppliers[supplier_id]
            self.offers.pop(supplier_id, None)
            if supplier_id in self._queue:
                self._queue.remove(supplier_id)
            self._rebuild()
        (self.dir / "offers" / f"{supplier_id}.json").unlink(missing_ok=True)
        self.save()

    def get(self, supplier_id: str) -> Supplier:
        with self._lock:
            supplier = self.suppliers.get(supplier_id)
        if supplier is None:
            raise KeyError(supplier_id)
        return supplier

    def by_host(self, host: str) -> Supplier | None:
        with self._lock:
            return next((s for s in self.suppliers.values() if s.site and _host(s.site) == host), None)

    def sample(self, supplier_id: str, limit: int = 20) -> list[SupplierOffer]:
        with self._lock:
            offers = list(self.offers.get(supplier_id, []))
        step = max(1, len(offers) // limit) if offers else 1
        return offers[::step][:limit]

    # ---------- предложения ----------

    def _to_offers(self, supplier: Supplier, extracted: list[Extracted], today: str, seen: set[tuple[str, float]]) -> list[SupplierOffer]:
        offers: list[SupplierOffer] = []
        for e in extracted:
            key = (normalize_name(e.name), e.price)
            if not e.name or e.price <= 0 or key in seen:
                continue
            seen.add(key)
            offers.append(SupplierOffer(supplier_id=supplier.id, supplier=supplier.name, name=e.name[:300], price=e.price, url=e.url[:500], sku=e.sku[:100], collected_at=today))
        return offers

    def set_offers(self, supplier_id: str, extracted: list[Extracted], source: str, kind: str | None = None, crawled: bool | None = None, keep_existing: bool = False) -> Supplier:
        """Заменить предложения поставщика (обход, прайс). keep_existing — старые предложения с
        другими названиями остаются (страницы из автопоиска, не попавшие в обход)."""
        supplier = self.get(supplier_id)
        today = _today()
        with self._lock:
            seen: set[tuple[str, float]] = set()
            offers = self._to_offers(supplier, extracted, today, seen)
            if keep_existing:
                old = [Extracted(name=o.name, price=o.price, url=o.url, sku=o.sku) for o in self.offers.get(supplier_id, [])]
                offers += self._to_offers(supplier, old, today, seen)
            self.offers[supplier_id] = offers
            supplier.offers = len(offers)
            supplier.collected_at = today
            supplier.source = source[:300]
            supplier.status = "done"
            supplier.progress = ""
            supplier.error = ""
            if kind:
                supplier.kind = kind  # type: ignore[assignment]
            if crawled is not None:
                supplier.crawled = crawled
            self.updated_at = today
            self._rebuild()
        self.save()
        return supplier

    def append_offers(self, supplier_id: str, extracted: list[Extracted], source: str) -> Supplier:
        """Добавить предложения (страницы из автопоиска) к уже собранным; дубли отбрасываются."""
        supplier = self.get(supplier_id)
        today = _today()
        with self._lock:
            existing = self.offers.setdefault(supplier_id, [])
            seen = {(normalize_name(o.name), o.price) for o in existing}
            new = self._to_offers(supplier, extracted, today, seen)
            if new:
                existing.extend(new)
                self._matcher.add(new)
            supplier.offers = len(existing)
            supplier.collected_at = today
            if supplier.status in ("idle", "error"):
                supplier.status = "done"
                supplier.error = ""
            if not supplier.source:
                supplier.source = source[:300]
            self.updated_at = today
        self.save()
        return supplier

    def discover(self, host: str, site_name: str, query: str, extracted: list[Extracted]) -> Supplier:
        """Магазин, найденный автопоиском: завести (если нового), добавить его предложения,
        поставить в очередь на обход каталога."""
        supplier = self.by_host(host)
        if supplier is None:
            supplier = Supplier(
                id=uuid.uuid4().hex[:8],
                name=(site_name or host)[:120],
                site=f"https://{host}",
                kind="site",
                discovered=True,
                query=query[:200],
                max_pages=max(50, self.autocrawl_pages or DEFAULT_AUTOCRAWL_PAGES),
            )
            with self._lock:
                self.suppliers[supplier.id] = supplier
        self.append_offers(supplier.id, extracted, f"автопоиск: {query}")
        if self.autocrawl_pages > 0 and not supplier.crawled:
            self.enqueue_crawl(supplier.id)
        return supplier

    def import_price_list(self, supplier_id: str, content: bytes, file_name: str) -> Supplier:
        suffix = Path(file_name).suffix or ".xlsx"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            extracted = read_price_list(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
        if not extracted:
            raise ValueError("в файле не нашлось строк с названием и ценой")
        supplier = self.get(supplier_id)
        return self.set_offers(supplier_id, extracted, f"прайс {file_name}", kind=None if supplier.site else "pricelist")

    # ---------- обход в фоне ----------

    def start_crawl(self, supplier_id: str) -> Supplier:
        supplier = self.get(supplier_id)
        if not supplier.site:
            raise ValueError("у поставщика не указан сайт — загрузите прайс-лист")
        with self._lock:
            job = self._jobs.get(supplier_id)
            if job is not None and job.is_alive() or supplier.status == "running":
                raise RuntimeError("обход уже идёт")
            if supplier_id in self._queue:
                self._queue.remove(supplier_id)
            self._begin(supplier)
            thread = threading.Thread(target=self._run_crawl, args=(supplier_id,), name=f"crawl-{supplier_id}", daemon=True)
            self._jobs[supplier_id] = thread
        thread.start()
        return supplier

    def enqueue_crawl(self, supplier_id: str) -> None:
        """Обход в общей очереди (по одному сайту за раз) — для найденных автопоиском."""
        with self._lock:
            supplier = self.suppliers.get(supplier_id)
            if supplier is None or not supplier.site or supplier.status == "running" or supplier_id in self._queue:
                return
            self._queue.append(supplier_id)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._drain_queue, name="crawl-queue", daemon=True)
                self._worker.start()

    def stop_crawl(self, supplier_id: str) -> None:
        with self._lock:
            if supplier_id in self._queue:
                self._queue.remove(supplier_id)
            supplier = self.suppliers.get(supplier_id)
            if supplier is not None and supplier.status == "running":
                self._stop.add(supplier_id)

    def wait(self, supplier_id: str, timeout: float | None = None) -> None:
        job = self._jobs.get(supplier_id)
        if job is not None:
            job.join(timeout)
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout)

    def _begin(self, supplier: Supplier) -> None:
        self._stop.discard(supplier.id)
        supplier.status = "running"
        supplier.progress = "начинаем"
        supplier.error = ""

    def _drain_queue(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    return
                supplier_id = self._queue.popleft()
                supplier = self.suppliers.get(supplier_id)
                if supplier is None or supplier.status == "running":
                    continue
                self._begin(supplier)
            self._run_crawl(supplier_id)

    def _run_crawl(self, supplier_id: str) -> None:
        supplier = self.get(supplier_id)

        def progress(text: str) -> None:
            with self._lock:
                supplier.progress = text

        factory = self._crawler_factory or (lambda **kw: SiteCrawler(**kw))
        crawler = factory(max_pages=supplier.max_pages, progress=progress, should_stop=lambda: supplier_id in self._stop)
        try:
            result = crawler.crawl(supplier.site)
        except Exception as exc:  # noqa: BLE001 — ошибка обхода не должна уронить сервис
            result = None
            error = f"{type(exc).__name__}: {exc}"[:300]
        else:
            error = result.error
        stopped = supplier_id in self._stop
        if result is not None and result.offers:
            self.set_offers(supplier_id, result.offers, result.source + (" (остановлен)" if stopped else ""), crawled=not stopped, keep_existing=True)
            return
        with self._lock:
            supplier.status = "error"
            supplier.progress = ""
            supplier.error = "остановлен, цен не собрано" if stopped else (error or f"цен не найдено (страниц просмотрено: {result.pages if result else 0}) — на сайте нет разметки цен, попробуйте прайс-лист")
        self.save()

    # ---------- поиск ----------

    def _rebuild(self) -> None:
        self._matcher = OfferMatcher([o for offers in self.offers.values() for o in offers])

    @property
    def description(self) -> str:
        with self._lock:
            total = sum(len(o) for o in self.offers.values())
            return f"каталоги поставщиков: {total} позиций у {len(self.suppliers)} поставщиков"

    def rank(self, name: str) -> list[tuple[SupplierOffer, float]]:
        """Предложения индекса по убыванию совпадения (не ниже порога «похоже»)."""
        with self._lock:
            return self._matcher.search(name)

    @staticmethod
    def matched_shops(ranked: list[tuple[SupplierOffer, float]]) -> int:
        """Сколько разных магазинов дали ту же позицию (совпадение не ниже MATCH_THRESHOLD)."""
        return len({offer.supplier_id for offer, score in ranked if score >= MATCH_THRESHOLD})

    def lookup(self, name: str, description: str, unit: str, today: str) -> InternetLookup:
        return self.build_lookup(self.rank(name), name, description, today)

    def build_lookup(self, ranked: list[tuple[SupplierOffer, float]], name: str, description: str, today: str) -> InternetLookup:
        query = re.sub(r"\s+", " ", f"{name} {description}".strip())[:300]
        if not ranked:
            return InternetLookup(status="not_found", query=query, looked_up_at=today, provider="suppliers", comment="в каталогах поставщиков похожих позиций нет")
        shown = ranked[:OFFERS_SHOWN]
        offers = [
            InternetOffer(
                title=offer.name,
                url=offer.url,
                shop=offer.supplier,
                price=offer.price,
                analog=score < MATCH_THRESHOLD,
                note=f"совпадение {round(score * 100)}%" + (f", арт. {offer.sku}" if offer.sku else "") + (f", цена от {offer.collected_at}" if offer.collected_at else ""),
            )
            for offer, score in shown
        ]
        matched = [offer.price for offer, score in ranked if score >= MATCH_THRESHOLD]
        if matched:
            price = float(statistics.median(matched))
            suppliers = len({offer.supplier for offer, score in ranked if score >= MATCH_THRESHOLD})
            low, high = (f"{value:,.0f}".replace(",", " ") for value in (min(matched), max(matched)))
            comment = f"совпадений {len(matched)} у {suppliers} поставщ., от {low} до {high} ₽; взята медиана"
        else:
            price = None
            comment = "точных совпадений нет, показаны похожие позиции — цену выбирает оператор"
        return InternetLookup(status="found", query=query, looked_up_at=today, offers=offers, price=price, comment=comment, provider="suppliers")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
