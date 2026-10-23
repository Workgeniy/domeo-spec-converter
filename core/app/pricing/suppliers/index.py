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
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ...models import InternetLookup, InternetOffer, SearchParam, Supplier, SupplierIndexInfo, SupplierOffer
from ..attributes import ManualParams, Wanted, compare_manual, compare_wanted, described_params, parse_params
from ..history import analyze_name, normalize_name
from ..model_ref import ModelRef, code_tokens, reference_model
from ..params import Params, compare_params, extract_params
from ..synonyms import RUSSIAN_WORD, stem
from .crawler import SiteCrawler, normalize_site
from .extract import Extracted, looks_like_listing, product_name
from .xlsx_import import read_price_list

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / ".data"
MOSCOW = ZoneInfo("Europe/Moscow")
MATCH_THRESHOLD = 0.6  # с этой оценки считаем, что предложение — та же позиция
ANALOG_THRESHOLD = 0.45  # ниже — не показываем даже как похожее (одно общее слово из трёх — ещё не похоже)
OFFERS_SHOWN = 6
DEFAULT_AUTOCRAWL_PAGES = 300
DEFAULT_MIN_SHOPS = 3  # столько разных магазинов по позиции считаем «картиной рынка»
# Зеркала магазинов на доменах стран СНГ/Балтии дают цену в местной валюте (та же миска:
# entero.by — 20, entero.ru — 545, entero.uz — 102 348): для рублёвой цены берём только рынок РФ.
BLOCKED_TLDS = frozenset({"by", "ua", "kz", "uz", "am", "az", "ge", "kg", "tj", "tm", "md", "ee", "lv", "lt"})
# Завышенная цена-выброс (опт, промышленное исполнение, ошибка разметки) не должна тянуть
# медиану вверх: при ≥4 ценах отбрасываем те, что выше медианы больше чем в OUTLIER_FACTOR раз.
# Низкие цены не трогаем — это обычно бюджетный, но подходящий товар, а занижать смету опаснее.
OUTLIER_FACTOR = 5.0
OUTLIER_MIN_COUNT = 4
# Если после отбора цены всё равно расходятся в разы, одним числом рынок не описать (у «холодильника
# 95 л» и бытовые, и лабораторные): предупреждаем оператора вместо тихой медианы.
DISPERSION_FACTOR = 8.0


def _today() -> str:
    return datetime.now(MOSCOW).date().isoformat()


def _host(site: str) -> str:
    host = urlsplit(site).netloc.lower() if "://" in site else site.lower()
    return host[4:] if host.startswith("www.") else host


def _foreign_market(url: str) -> bool:
    """Домен не российского рынка — цена в чужой валюте. Пустой url (прайс без ссылки) — доверяем."""
    host = _host(url).split(":")[0]
    return "." in host and host.rsplit(".", 1)[-1] in BLOCKED_TLDS


PARAM_MATCH_BONUS = 0.1
PARAM_CONFLICT_FACTOR = 0.75
SECTION_BONUS = 0.05
PLACEHOLDER_PRICE = 1.0  # «1 ₽» у магазинов — заглушка «цена по запросу», а не цена
NOTE_PARAMS_MATCH = "параметры совпали"
NOTE_PARAMS_PARTIAL = "параметры совпали не все: часть не указана"
NOTE_PARAMS_CONFLICT = "параметры не совпали"
NOTE_PARAMS_UNKNOWN = "параметры не указаны"
NOTE_CATEGORY = "похоже на детскую игрушку — другой тип товара"
PLURAL_ENDINGS = ("ы", "и", "ья")  # стулья, столы, стеллажи — так магазины называют разделы каталога
# Товар для оснащения помещения — оборудование, а не игрушка с тем же названием («музыкальный
# центр» для зала vs детская игрушка). Если сама позиция не игрушка, а предложение явно игрушка,
# не даём ему задавать цену (оставляем только как похожее). Маркеры узкие, чтобы не задеть
# «развивающие пособия»/«детскую мебель», которые детсад закупает всерьёз.
_TOY_MARKERS = re.compile(r"игрушк|развивающ", re.I)


def _is_toy(text: str) -> bool:
    return bool(_TOY_MARKERS.search(text))


class Ranked(NamedTuple):
    """Предложение индекса с оценкой совпадения."""

    offer: SupplierOffer
    score: float
    note: str  # пометка о параметрах
    alias: str = ""  # совпало с названием позиции у поставщика из истории закупок, а не с нашим
    confirmed: bool = False  # у предложения подтверждены все параметры, которые задал оператор
    model: bool = False  # та же модель, что в графе «Тип, марка» проекта
    matched: int = 0  # сколько параметров совпало — при равной оценке выше тот, у кого больше


class OfferMatcher:
    """Индекс слово → предложения; оценка по словам та же, что у сопоставления с историей,
    плюс эталонная модель из графы «Тип, марка» (model_ref.py), проверка числовых параметров
    (габариты, объём, масса…), материала и признаков из характеристик и параметров оператора
    (attributes.py) и проверка, что это тот же товар, а не соседний с теми же словами."""

    def __init__(self, offers: list[SupplierOffer] | None = None):
        self.offers: list[SupplierOffer] = []
        self.index: dict[str, set[int]] = defaultdict(set)
        self.offer_tokens: list[set[str]] = []
        self.offer_keys: list[str] = []
        self.offer_params: list[Params] = []
        self.offer_heads: list[str] = []  # главное слово (основа), если наименование начинается с существительного
        self.offer_head_words: list[str] = []  # главное слово как написано — для проверки числа
        self.offer_loose: list[set[str]] = []  # основы до и после замены оборотов — для проверки общих слов
        self.offer_codes: list[tuple[str, ...]] = []  # слова названия как коды моделей
        self.offer_compact: list[str] = []  # они же слитно — быстрый отбор по коду модели
        self.offer_toy: list[bool] = []  # предложение похоже на детскую игрушку
        self.add(offers or [])

    def add(self, offers: list[SupplierOffer]) -> None:
        for offer in offers:
            title = product_name(offer.name)  # без хвоста заголовка страницы, если он есть
            if offer.price <= PLACEHOLDER_PRICE or looks_like_listing(title) or _foreign_market(offer.url):
                continue  # заглушка вместо цены, страница раздела или чужой валютный рынок — не берём
            i = len(self.offers)
            self.offers.append(offer)
            info = analyze_name(title)
            self.offer_tokens.append(set(info.stems))
            self.offer_keys.append(info.key)
            self.offer_params.append(extract_params(title))
            self.offer_heads.append(info.head)
            self.offer_head_words.append(info.head_word)
            self.offer_loose.append(info.loose)
            codes = code_tokens(title)
            self.offer_codes.append(codes)
            self.offer_compact.append("".join(codes))
            self.offer_toy.append(_is_toy(title))
            for t in info.stems:
                self.index[t].add(i)

    def model_hits(self, model: ModelRef | None, name: str = "") -> set[int]:
        """Предложения с той же моделью, что в проекте, — по коду, даже если слова названия другие.
        Если у предложения своё главное слово и оно никак не перекликается с нашим наименованием
        («Шнурки … 100 см» для «Облучатель … 100С»), это не та модель, а совпадение букв."""
        if model is None or not model.probe:
            return set()
        own = analyze_name(name)
        own_words = set(own.stems)

        def same_kind(i: int) -> bool:
            if any(e not in self.offer_loose[i] for e in model.extra):
                return False  # «на подставке со скамьей» в проекте, а у предложения голый шкаф
            head = self.offer_heads[i]
            return not head or not own.head or head in own_words or own.head in self.offer_tokens[i]

        return {
            i
            for i, compact in enumerate(self.offer_compact)
            if model.probe in compact and model.matches(self.offer_codes[i]) and same_kind(i)
        }

    def search(
        self,
        name: str,
        description: str = "",
        section: str = "",
        aliases: Iterable[str] = (),
        manual: ManualParams | None = None,
        model: ModelRef | None = None,
    ) -> list[Ranked]:
        """Предложения по убыванию совпадения. Кроме нашего наименования, ищем и по названиям
        позиции у поставщиков из истории закупок (``aliases``) — такое совпадение помечается и
        засчитывается, только если у предложения есть хоть одно общее слово с нашим
        наименованием или оно начинается с марки: «Стол, цвет белый» по названию «Стол-мойка
        медицинский» — не «Тумба с мойкой». ``manual`` — параметры оператора: числовые
        сверяются вместе с характеристиками, текстовые — по названию предложения. ``model`` —
        эталон из «Тип, марка»: предложение с той же моделью — та же позиция."""
        manual = manual if manual is not None and manual.checkable() else None
        spec = extract_params(f"{name} {description} {manual.numeric_text if manual else ''}")
        described = described_params(name, description, manual)
        section_key = section.strip().lower()
        own_loose = analyze_name(name).loose
        same_model = self.model_hits(model, name)
        query_toy = _is_toy(f"{name} {description}")  # сама позиция — игрушка (тогда игрушки в предложениях уместны)
        best: dict[int, Ranked] = {}
        for query_name, alias in [(name, ""), *((a, a) for a in aliases)]:
            info = analyze_name(query_name)
            if not info.stems:
                continue
            query = set(info.stems)
            first = info.stems[0] if RUSSIAN_WORD.fullmatch(info.stems[0]) else ""
            candidates = set().union(*(self.index.get(t, ()) for t in query))
            if not alias:
                candidates |= same_model
            for i in candidates:
                if alias and not own_loose & self.offer_loose[i] and self.offer_heads[i]:
                    continue  # по чужому названию — только то, что хоть словом похоже на наше (или марка с моделью)
                ranked = self._rank(i, info.key, query, (first, info.head_word), spec, described, manual, section_key, alias, i in same_model, query_toy)
                if ranked is not None and (i not in best or ranked.score > best[i].score):
                    best[i] = ranked
        # При равном совпадении вперёд идёт модель из проекта, потом предложения с подтверждёнными
        # параметрами, потом без указанных.
        order = {NOTE_PARAMS_MATCH: 0, NOTE_PARAMS_PARTIAL: 1, "": 2, NOTE_PARAMS_UNKNOWN: 2, NOTE_PARAMS_CONFLICT: 3, NOTE_CATEGORY: 3}
        return sorted(best.values(), key=lambda r: (-r.score, not r.model, not r.confirmed, order[r.note], -r.matched, r.offer.price))

    def _rank(
        self,
        i: int,
        key: str,
        query: set[str],
        head: tuple[str, str],
        spec: Params,
        described: list[Wanted],
        manual: ManualParams | None,
        section_key: str,
        alias: str,
        same_model: bool,
        query_toy: bool = False,
    ) -> Ranked | None:
        score, common = self._score(key, query, i)
        if same_model:
            score = 1.0  # та же модель, что назвал проектировщик, — та же позиция, как бы ни звалась
        offer = self.offers[i]
        if section_key and offer.section and offer.section.strip().lower() == section_key:
            score = min(1.0, round(score + SECTION_BONUS, 3))  # прайс того же раздела — чуть надёжнее
        note = ""
        confirmed = False
        matches = 0
        if not spec.empty() or described or manual is not None:
            matches, conflicts, missing = compare_params(spec, self.offer_params[i]) if not spec.empty() else (0, 0, 0)
            evidence = matches  # что прибавляет к оценке: числа и параметры оператора
            if described:
                # Материал и признаки из характеристик отводят противоречащее и поднимают совпавшее
                # в списке, но к оценке не прибавляют: «электрическая» не делает бытовую плиту
                # той же позицией, что промышленная.
                m, c, x = compare_wanted(described, self.offer_keys[i], self.offer_loose[i])
                matches, conflicts, missing = matches + m, conflicts + c, missing + x
            if manual is not None:
                verdict = compare_manual(manual, self.offer_keys[i], self.offer_loose[i], self.offer_params[i])
                matches, conflicts, missing = matches + verdict.matches, conflicts + verdict.conflicts, missing + verdict.missing
                evidence += verdict.matches
                # Модель из проекта — сама по себе подтверждение, если ничто ей не противоречит.
                confirmed = verdict.confirmed or (same_model and not conflicts)
            if conflicts:
                # Другой размер/объём/материал — это не та же позиция: не выше «похожего», в цену не входит.
                score = min(round(score * PARAM_CONFLICT_FACTOR, 3), MATCH_THRESHOLD - 0.01)
                note = NOTE_PARAMS_CONFLICT
            elif matches:
                if evidence:
                    score = min(1.0, round(score + PARAM_MATCH_BONUS, 3))
                # «Совпали не все»: например, число полок то же, а размера у продавца нет.
                note = NOTE_PARAMS_PARTIAL if missing else NOTE_PARAMS_MATCH
            else:
                note = NOTE_PARAMS_UNKNOWN
        if self.offer_toy[i] and not query_toy and not same_model:
            # Детская игрушка для неигрушечной позиции («музыкальный центр» для зала) — другой тип
            # товара: цену не задаёт, остаётся только как похожее.
            score = min(score, round(MATCH_THRESHOLD - 0.01, 3))
            note = NOTE_CATEGORY
        if score >= MATCH_THRESHOLD and not same_model and not self._same_item(query, head, common, i):
            score = round(MATCH_THRESHOLD - 0.01, 3)  # слова похожи, товар другой — в цену не входит
        return Ranked(offer, score, note, alias, confirmed, same_model, matches) if score >= ANALOG_THRESHOLD else None

    def _score(self, key: str, query: set[str], i: int) -> tuple[float, int]:
        """Оценка по словам и число общих слов."""
        candidate = self.offer_tokens[i]
        if not candidate:
            return 0.0, 0
        common = len(query & candidate)
        if self.offer_keys[i] == key:
            return 1.0, common
        score = 0.65 * common / len(query) + 0.35 * common / len(candidate)
        if self.offer_keys[i].startswith(key[:20]) or key.startswith(self.offer_keys[i][:20]):
            score = min(1.0, score + 0.15)
        return round(score, 3), common

    def _same_item(self, query: set[str], head: tuple[str, str], common: int, i: int) -> bool:
        """Тот ли это товар, а не соседний с теми же словами: общих слов не меньше двух (если в
        запросе их два и больше), первое слово запроса есть в предложении, главное слово
        предложения — в запросе, и предложение не во множественном числе там, где в проекте
        единственное. Иначе «Столы» (страница раздела) сошлись бы со «Стол воспитателя»,
        «Перегородка-стеллаж» — со «Стеллаж металлический», «Карнизы для штор» — со «Штора с карнизом»."""
        first, number_word = head
        if len(query) >= 2 and common < 2:
            return False
        if first and first not in self.offer_tokens[i]:
            return False
        offer_head = self.offer_heads[i]
        if offer_head and offer_head not in query:
            return False
        return not _plural_for_singular(number_word, self.offer_head_words[i])


def _plural_for_singular(query_word: str, offer_word: str) -> bool:
    """У магазина главное слово во множественном числе («Стулья с пюпитром», «Кресла»), а в
    проекте — в единственном: это раздел каталога с ценой «от», а не товар."""
    if not query_word or not offer_word:
        return False
    if offer_word.endswith(PLURAL_ENDINGS) and not query_word.endswith(PLURAL_ENDINGS):
        return True
    # Средний род: кресло → кресла, зеркало → зеркала (у женского рода «-а» — единственное число).
    return offer_word.endswith(("а", "я")) and query_word.endswith(("о", "е")) and stem(offer_word) == stem(query_word)


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

    def add(self, name: str, site: str = "", max_pages: int = 3000, sections: list[str] | None = None) -> Supplier:
        name = " ".join(name.split())
        if not name:
            raise ValueError("не указано название поставщика")
        site = normalize_site(site) if site.strip() else ""
        supplier = Supplier(
            id=uuid.uuid4().hex[:8],
            name=name,
            site=site,
            kind="site" if site else "pricelist",
            max_pages=max(50, min(max_pages, 50_000)),
            sections=_clean_sections(sections),
        )
        with self._lock:
            self.suppliers[supplier.id] = supplier
        self.save()
        return supplier

    def update(self, supplier_id: str, name: str | None = None, sections: list[str] | None = None, max_pages: int | None = None) -> Supplier:
        supplier = self.get(supplier_id)
        with self._lock:
            if name is not None and " ".join(name.split()):
                supplier.name = " ".join(name.split())
                for offer in self.offers.get(supplier_id, []):
                    offer.supplier = supplier.name
            if sections is not None:
                supplier.sections = _clean_sections(sections)
            if max_pages is not None:
                supplier.max_pages = max(50, min(int(max_pages), 50_000))
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

    def _to_offers(self, supplier: Supplier, extracted: list[Extracted], today: str, seen: set[tuple[str, float]], section: str = "") -> list[SupplierOffer]:
        offers: list[SupplierOffer] = []
        for e in extracted:
            key = (normalize_name(e.name), e.price)
            if not e.name or e.price <= 0 or key in seen:
                continue
            seen.add(key)
            offers.append(
                SupplierOffer(supplier_id=supplier.id, supplier=supplier.name, name=e.name[:300], price=e.price, url=e.url[:500], sku=e.sku[:100], collected_at=today, section=section)
            )
        return offers

    def set_offers(
        self,
        supplier_id: str,
        extracted: list[Extracted],
        source: str,
        kind: str | None = None,
        crawled: bool | None = None,
        keep_existing: bool = False,
        section: str = "",
    ) -> Supplier:
        """Заменить предложения поставщика (обход, прайс). keep_existing — старые предложения с
        другими названиями остаются (страницы из автопоиска, не попавшие в обход)."""
        supplier = self.get(supplier_id)
        today = _today()
        with self._lock:
            seen: set[tuple[str, float]] = set()
            offers = self._to_offers(supplier, extracted, today, seen, section)
            if keep_existing:
                old = self.offers.get(supplier_id, [])
                for o in old:
                    if (normalize_name(o.name), o.price) not in seen:
                        seen.add((normalize_name(o.name), o.price))
                        offers.append(o.model_copy(update={"collected_at": today}))
            if section and section not in supplier.sections:
                supplier.sections = _clean_sections(supplier.sections + [section])
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

    def import_price_list(self, supplier_id: str, content: bytes, file_name: str, section: str = "") -> Supplier:
        """Прайс xlsx. С разделом — заменяет только цены этого раздела (прайсы по разделам
        приходят от поставщика разными файлами), без раздела — все цены поставщика."""
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
        section = " ".join(section.split())
        if section:
            with self._lock:
                self.offers[supplier_id] = [o for o in self.offers.get(supplier_id, []) if o.section != section]
            source = f"прайс «{section}» {file_name}"
        else:
            source = f"прайс {file_name}"
        return self.set_offers(supplier_id, extracted, source, kind=None if supplier.site else "pricelist", keep_existing=bool(section), section=section)

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

    def rank(
        self,
        name: str,
        description: str = "",
        section: str = "",
        aliases: Iterable[str] = (),
        params: Iterable[SearchParam] = (),
        type_mark: str = "",
    ) -> list[Ranked]:
        """Предложения индекса по убыванию совпадения (не ниже порога «похоже»); параметры из
        характеристик и заданные оператором (``params``) подтверждают или отводят совпадение,
        прайс того же раздела — небольшой плюс, модель из «Тип, марка» (``type_mark``) — та же
        позиция. ``aliases`` — названия позиции у поставщиков из истории закупок: подключаются,
        когда по нашему названию меньше ``min_shops`` магазинов."""
        manual = parse_params(params)
        model = reference_model(type_mark)
        with self._lock:
            ranked = self._matcher.search(name, description, section, manual=manual, model=model)
            if aliases and self.matched_shops(ranked, manual.checkable()) < self.min_shops:
                # По нашему названию рынка не хватает — добавляем найденное по названиям из истории.
                ranked = self._matcher.search(name, description, section, aliases, manual, model)
            return ranked

    @staticmethod
    def matched_shops(ranked: list[Ranked], confirmed_only: bool = False) -> int:
        """Сколько разных магазинов дали ту же позицию (совпадение не ниже MATCH_THRESHOLD);
        ``confirmed_only`` — только с подтверждёнными параметрами оператора."""
        return len({r.offer.supplier_id for r in ranked if r.score >= MATCH_THRESHOLD and (r.confirmed or not confirmed_only)})

    def lookup(
        self,
        name: str,
        description: str,
        unit: str,
        today: str,
        section: str = "",
        aliases: Iterable[str] = (),
        params: Iterable[SearchParam] = (),
        type_mark: str = "",
    ) -> InternetLookup:
        params = list(params)
        return self.build_lookup(self.rank(name, description, section, aliases, params, type_mark), name, description, today, params, type_mark)

    def build_lookup(
        self, ranked: list[Ranked], name: str, description: str, today: str, params: Iterable[SearchParam] = (), type_mark: str = ""
    ) -> InternetLookup:
        """Ответ по ранжированным предложениям. Рекомендуемая цена — медиана по совпавшим, а
        если среди них есть подтвердившие параметры оператора — по ним; без параметров
        оператора, но с моделью из проекта среди совпавших — по этой модели."""
        query = re.sub(r"\s+", " ", f"{name} {description}".strip())[:300]
        manual = parse_params(params)
        model = reference_model(type_mark)
        spec = extract_params(f"{name} {description}")
        described = described_params(name, description, manual if manual.checkable() else None)
        from_description = [spec.describe(counts=True)] if not spec.empty() else []
        from_description += [w.label for w in described]
        params_text = f"параметры из характеристик: {', '.join(from_description)}" if from_description else ""
        manual_text = f"параметры оператора: {manual.describe()}" if not manual.empty() else ""
        model_text = f"модель в проекте: {model.text}" if model is not None else ""
        if not ranked:
            comment = "; ".join(p for p in (model_text, manual_text, "в каталогах поставщиков похожих позиций нет") if p)
            return InternetLookup(status="not_found", query=query, looked_up_at=today, provider="suppliers", comment=comment)
        offers = [
            InternetOffer(
                title=r.offer.name,
                url=r.offer.url,
                shop=r.offer.supplier,
                price=r.offer.price,
                analog=r.score < MATCH_THRESHOLD,
                note=", ".join(
                    part
                    for part in (
                        "модель как в проекте" if r.model else f"совпадение {round(r.score * 100)}%",
                        f"по названию из истории закупок «{r.alias[:60]}»" if r.alias else "",
                        r.note,
                        f"раздел «{r.offer.section}»" if r.offer.section else "",
                        f"арт. {r.offer.sku}" if r.offer.sku else "",
                        f"цена от {r.offer.collected_at}" if r.offer.collected_at else "",
                    )
                    if part
                ),
            )
            for r in ranked[:OFFERS_SHOWN]
        ]
        confident = [r for r in ranked if r.score >= MATCH_THRESHOLD]
        confirmed = [r for r in confident if r.confirmed]
        same_model = [r for r in confident if r.model]
        if confirmed:
            chosen, kind = confirmed, "confirmed"
        elif same_model and not manual.checkable():
            chosen, kind = same_model, "model"
        else:
            chosen, kind = confident, "all"
        basis = _without_outliers(chosen)  # цены-выбросы (опт, лаборатория, ошибка) медиану не тянут
        if basis:
            prices = [r.offer.price for r in basis]
            price = float(statistics.median(prices))
            suppliers = len({r.offer.supplier for r in basis})
            low, high = (f"{value:,.0f}".replace(",", " ") for value in (min(prices), max(prices)))
            dropped = len(chosen) - len(basis)
            comment = f"совпадений {len(prices)} у {suppliers} поставщ., от {low} до {high} ₽; взята медиана"
            if dropped:
                comment += f" (ещё {dropped} с ценой-выбросом отброшены)"
            if kind == "confirmed":
                comment = f"с заданными параметрами {comment}"
                if len(confirmed) < len(confident):
                    comment += f"; ещё {len(confident) - len(confirmed)} без подтверждения параметров в цену не вошли"
            elif kind == "model":
                comment = f"по модели из проекта {comment}"
                if len(same_model) < len(confident):
                    comment += f"; ещё {len(confident) - len(same_model)} других моделей в цену не вошли"
            elif manual.checkable():
                comment += "; заданные параметры в предложениях не подтверждены — проверьте"
            elif params_text and all(r.note == NOTE_PARAMS_UNKNOWN for r in confident):
                comment += "; в предложениях параметры не указаны — проверьте размер"
            elif params_text and not any(r.note == NOTE_PARAMS_MATCH for r in confident):
                comment += "; в предложениях указаны не все параметры — проверьте размер"
            if min(prices) > 0 and max(prices) / min(prices) >= DISPERSION_FACTOR:
                comment += "; большой разброс цен — проверьте, не попали ли изделия другого класса"
        else:
            price = None
            comment = "точных совпадений нет, показаны похожие позиции — цену выбирает оператор"
            if (params_text or manual.checkable()) and any(r.note == NOTE_PARAMS_CONFLICT for r in ranked):
                comment = "по словам похоже, но параметры другие — цену выбирает оператор"
        if model is not None and not any(r.model for r in ranked):
            model_text += " — в каталогах её нет, цена по похожим"
        comment = "; ".join(p for p in (model_text, manual_text, params_text, comment) if p)
        return InternetLookup(status="found", query=query, looked_up_at=today, offers=offers, price=price, comment=comment, provider="suppliers")


def _without_outliers(basis: list[Ranked]) -> list[Ranked]:
    """Убирает завышенные ценовые выбросы перед расчётом цены: при достаточном числе предложений —
    те, что выше медианы больше чем в OUTLIER_FACTOR раз (опт, промышленное исполнение, ошибка
    разметки). Низкие цены оставляем: это обычно бюджетный, но подходящий товар."""
    if len(basis) < OUTLIER_MIN_COUNT:
        return basis
    med = statistics.median([r.offer.price for r in basis])
    if med <= 0:
        return basis
    kept = [r for r in basis if r.offer.price <= med * OUTLIER_FACTOR]
    return kept if 2 <= len(kept) < len(basis) else basis


def _clean_sections(sections: list[str] | None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in sections or []:
        section = " ".join(str(raw).split())[:60]
        if section and section.lower() not in seen:
            seen.add(section.lower())
            result.append(section)
    return result


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
