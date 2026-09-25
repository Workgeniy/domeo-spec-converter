"""Индекс цен поставщиков: список поставщиков, их предложения на диске, обход сайтов в фоне
и поиск по индексу для позиций спецификации (в той же форме, что и поиск в интернете).

Хранение: ``DATA_DIR/suppliers/index.json`` (поставщики) и ``offers/<id>.json`` (их
предложения). Обход одного поставщика — отдельный поток; одновременно один обход на
поставщика, статус и прогресс видны через ``info()``.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import tempfile
import threading
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
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


def _today() -> str:
    return datetime.now(MOSCOW).date().isoformat()


class OfferMatcher:
    """Индекс слово → предложения; оценка та же, что у сопоставления с историей."""

    def __init__(self, offers: list[SupplierOffer]):
        self.offers = offers
        self.index: dict[str, set[int]] = defaultdict(set)
        self.offer_tokens: list[set[str]] = []
        self.offer_keys: list[str] = []
        for i, offer in enumerate(offers):
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
        ranked = sorted(((self.offers[i], s) for i, s in scored.items() if s >= ANALOG_THRESHOLD), key=lambda pair: (-pair[1], pair[0].price))
        return ranked

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
        self._matcher = OfferMatcher([])
        self._lock = threading.RLock()
        self._jobs: dict[str, threading.Thread] = {}
        self._stop: set[str] = set()
        self._crawler_factory = None  # для тестов: подменить SiteCrawler

    # ---------- хранение ----------

    def load(self) -> None:
        index_file = self.dir / "index.json"
        if not index_file.exists():
            return
        raw = json.loads(index_file.read_text(encoding="utf-8"))
        with self._lock:
            self.updated_at = raw.get("updated_at", "")
            for item in raw.get("suppliers", []):
                supplier = Supplier.model_validate(item)
                if supplier.status == "running":  # обход прервался перезапуском сервиса
                    supplier.status = "error"
                    supplier.error = "обход прерван перезапуском сервиса"
                self.suppliers[supplier.id] = supplier
                offers_file = self.dir / "offers" / f"{supplier.id}.json"
                if offers_file.exists():
                    self.offers[supplier.id] = [SupplierOffer.model_validate(o) for o in json.loads(offers_file.read_text(encoding="utf-8"))]
            self._rebuild()

    def save(self) -> None:
        (self.dir / "offers").mkdir(parents=True, exist_ok=True)
        with self._lock:
            payload = {"updated_at": self.updated_at, "suppliers": [s.model_dump() for s in self.suppliers.values()]}
            snapshot = {sid: [o.model_dump() for o in offers] for sid, offers in self.offers.items()}
        _write_json(self.dir / "index.json", payload)
        for sid, offers in snapshot.items():
            _write_json(self.dir / "offers" / f"{sid}.json", offers)

    # ---------- поставщики ----------

    def info(self) -> SupplierIndexInfo:
        with self._lock:
            suppliers = sorted(self.suppliers.values(), key=lambda s: s.name.lower())
            return SupplierIndexInfo(suppliers=[s.model_copy() for s in suppliers], offers=sum(len(o) for o in self.offers.values()), updated_at=self.updated_at)

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
            self._rebuild()
        offers_file = self.dir / "offers" / f"{supplier_id}.json"
        offers_file.unlink(missing_ok=True)
        self.save()

    def get(self, supplier_id: str) -> Supplier:
        with self._lock:
            supplier = self.suppliers.get(supplier_id)
        if supplier is None:
            raise KeyError(supplier_id)
        return supplier

    def sample(self, supplier_id: str, limit: int = 20) -> list[SupplierOffer]:
        with self._lock:
            offers = list(self.offers.get(supplier_id, []))
        step = max(1, len(offers) // limit) if offers else 1
        return offers[::step][:limit]

    def set_offers(self, supplier_id: str, extracted: list[Extracted], source: str, kind: str | None = None) -> Supplier:
        supplier = self.get(supplier_id)
        today = _today()
        with self._lock:
            # Один товар встречается на нескольких страницах каталога (листинги) — оставляем первое вхождение.
            seen: set[tuple[str, float]] = set()
            offers: list[SupplierOffer] = []
            for e in extracted:
                key = (normalize_name(e.name), e.price)
                if not e.name or e.price <= 0 or key in seen:
                    continue
                seen.add(key)
                offers.append(SupplierOffer(supplier_id=supplier_id, supplier=supplier.name, name=e.name[:300], price=e.price, url=e.url[:500], sku=e.sku[:100], collected_at=today))
            self.offers[supplier_id] = offers
            supplier.offers = len(offers)
            supplier.collected_at = today
            supplier.source = source[:300]
            supplier.status = "done"
            supplier.progress = ""
            supplier.error = ""
            if kind:
                supplier.kind = kind  # type: ignore[assignment]
            self.updated_at = today
            self._rebuild()
        self.save()
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
            if job is not None and job.is_alive():
                raise RuntimeError("обход уже идёт")
            self._stop.discard(supplier_id)
            supplier.status = "running"
            supplier.progress = "начинаем"
            supplier.error = ""
            thread = threading.Thread(target=self._run_crawl, args=(supplier_id,), name=f"crawl-{supplier_id}", daemon=True)
            self._jobs[supplier_id] = thread
        thread.start()
        return supplier

    def stop_crawl(self, supplier_id: str) -> None:
        with self._lock:
            job = self._jobs.get(supplier_id)
            if job is not None and job.is_alive():
                self._stop.add(supplier_id)

    def wait(self, supplier_id: str, timeout: float | None = None) -> None:
        job = self._jobs.get(supplier_id)
        if job is not None:
            job.join(timeout)

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
            self.set_offers(supplier_id, result.offers, result.source + (" (остановлен)" if stopped else ""))
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

    def lookup(self, name: str, description: str, unit: str, today: str) -> InternetLookup:
        query = re.sub(r"\s+", " ", f"{name} {description}".strip())[:300]
        ranked = self._matcher.search(name)
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
            comment = f"совпадений {len(matched)} у {suppliers} поставщ., от {min(matched):,.0f} до {max(matched):,.0f} ₽; взята медиана".replace(",", " ")
        else:
            price = None
            comment = "точных совпадений нет, показаны похожие позиции — цену выбирает оператор"
        return InternetLookup(status="found", query=query, looked_up_at=today, offers=offers, price=price, comment=comment, provider="suppliers")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
