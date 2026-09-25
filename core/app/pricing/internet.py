"""Цена из интернета на дату: поиск предложений моделью с веб-поиском.

Провайдер поиска — за протоколом ``PriceSearchProvider``. Сейчас это Claude с серверным
инструментом web_search: одна модель и ищет, и читает выдачу, и отбирает подходящие
предложения, и отдаёт JSON с ценами и ссылками. Результаты кэшируются в
``DATA_DIR/internet_prices.json`` на ``ttl_days`` — у каждой цены есть дата, поэтому
«цена на дату» остаётся честной, а повторный просчёт того же объекта ничего не стоит.
"""

from __future__ import annotations

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from ..models import InternetLookup, InternetOffer, InternetSearchInfo, MatchRequestItem
from .history import normalize_name

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / ".data"
DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "medium"
DEFAULT_MAX_SEARCHES = 4
DEFAULT_TTL_DAYS = 7
DEFAULT_CONCURRENCY = 3
MOSCOW = ZoneInfo("Europe/Moscow")
DESCRIPTION_LIMIT = 700
MAX_OFFERS = 6

SYSTEM_PROMPT = """Ты помощник отдела закупок компании, которая комплектует детские сады, школы и пищеблоки в России мебелью и оборудованием.
Задача: по позиции спецификации найти в интернете актуальные предложения российских продавцов и назвать цену на сегодня.

Правила:
- Подходят предложения того же типа товара с теми же ключевыми характеристиками (назначение, размеры, материал, комплектность). Если точно такого нет — можно привести похожие, пометив их как аналог и указав, чем отличаются.
- Цена — в рублях, с НДС, за одну единицу измерения из спецификации (за штуку, за комплект). Цены за другую единицу и явно устаревшие не бери.
- Годятся сайты производителей, магазинов и маркетплейсов, где цена видна на странице.
- Рекомендуемая цена — типичная среди подходящих предложений, а не самая низкая с сомнительной страницы. Если нашлись только аналоги — рекомендуй по ним и скажи об этом в комментарии.
- Если ничего подходящего не нашлось — верни пустой список предложений и price: null.

Ответ — только JSON без пояснений вокруг, по схеме:
{"offers": [{"title": "название предложения", "url": "ссылка на страницу", "shop": "продавец", "price": 12345.0, "analog": false, "note": "чем отличается, если аналог"}],
 "price": 12345.0,
 "comment": "коротко: что нашлось и почему такая цена"}"""


class PriceSearchProvider(Protocol):
    name: str
    model: str

    def lookup(self, name: str, description: str, unit: str, today: str) -> InternetLookup: ...


def today_moscow() -> str:
    return datetime.now(MOSCOW).date().isoformat()


def extract_json(text: str) -> dict[str, Any]:
    """JSON из ответа модели: снимает ограждение ```json и берёт внешний объект."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("в ответе модели нет JSON")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("в ответе модели не объект JSON")
    return payload


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^\d,.\-]", "", value).replace(",", ".")
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None
    return None


def parse_lookup(payload: dict[str, Any], *, query: str, today: str, provider: str, searches: int = 0) -> InternetLookup:
    """Ответ модели → InternetLookup. Рекомендуемая цена, если модель её не назвала, —
    медиана по точным предложениям (по аналогам, если точных нет)."""
    offers: list[InternetOffer] = []
    for raw in payload.get("offers") or []:
        if not isinstance(raw, dict):
            continue
        price = _to_float(raw.get("price"))
        if price is None or price <= 0:
            continue
        offers.append(
            InternetOffer(
                title=str(raw.get("title") or "")[:200],
                url=str(raw.get("url") or "")[:500],
                shop=str(raw.get("shop") or "")[:100],
                price=price,
                analog=bool(raw.get("analog")),
                note=str(raw.get("note") or "")[:300],
            )
        )
    offers = offers[:MAX_OFFERS]
    price = _to_float(payload.get("price"))
    if price is not None and price <= 0:
        price = None
    if price is None and offers:
        prices = sorted(o.price for o in offers if not o.analog) or sorted(o.price for o in offers)
        price = prices[len(prices) // 2]
    return InternetLookup(
        status="found" if offers else "not_found",
        query=query,
        looked_up_at=today,
        offers=offers,
        price=price,
        comment=str(payload.get("comment") or "")[:500],
        provider=provider,
        searches=searches,
    )


def build_query(name: str, description: str) -> str:
    """Что ищем — наименование и укороченные характеристики (в кэше и в интерфейсе)."""
    text = " ".join(part for part in (name.strip(), description.strip()) if part)
    return re.sub(r"\s+", " ", text)[:DESCRIPTION_LIMIT]


class ClaudeWebSearchProvider:
    """Claude с серверным web_search: модель сама ищет, читает страницы и отбирает предложения."""

    name = "claude-web-search"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        effort: str = DEFAULT_EFFORT,
        max_searches: int = DEFAULT_MAX_SEARCHES,
        timeout: float = 240.0,
    ):
        import anthropic  # ленивый импорт: без ключа SDK сервису не нужен

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=3)
        self.model = model
        self.effort = effort
        self.max_searches = max_searches

    def lookup(self, name: str, description: str, unit: str, today: str) -> InternetLookup:
        query = build_query(name, description)
        prompt = (
            f"Позиция спецификации: {name.strip()}\n"
            f"Характеристики: {description.strip()[:DESCRIPTION_LIMIT] or '—'}\n"
            f"Единица измерения: {unit.strip() or 'шт.'}\n"
            f"Сегодня: {today}.\n"
            "Найди актуальные предложения российских продавцов и верни JSON по схеме."
        )
        a = self._anthropic
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=4000,
                system=SYSTEM_PROMPT,
                output_config={"effort": self.effort},
                # На отказ по политике запрос сам уходит на запасную модель — без нашего кода.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                tools=[
                    {
                        "type": "web_search_20260209",
                        "name": "web_search",
                        "max_uses": self.max_searches,
                        "user_location": {"type": "approximate", "country": "RU", "timezone": "Europe/Moscow"},
                    }
                ],
                messages=[{"role": "user", "content": prompt}],
            )
        except a.AuthenticationError as exc:
            raise RuntimeError("ключ ANTHROPIC_API_KEY не принят") from exc
        except a.RateLimitError as exc:
            raise RuntimeError("превышен лимит запросов к модели, повторите позже") from exc
        except a.APIStatusError as exc:
            raise RuntimeError(f"ошибка API модели {exc.status_code}: {exc.message}") from exc
        except a.APIConnectionError as exc:
            raise RuntimeError("нет связи с API модели") from exc

        searches = 0
        server_use = getattr(response.usage, "server_tool_use", None)
        if server_use is not None:
            searches = int(getattr(server_use, "web_search_requests", 0) or 0)
        if response.stop_reason == "refusal":
            return InternetLookup(status="error", query=query, looked_up_at=today, comment="модель отказалась обрабатывать запрос", provider=self.name, searches=searches)
        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            payload = extract_json(text)
        except (ValueError, json.JSONDecodeError) as exc:
            return InternetLookup(status="error", query=query, looked_up_at=today, comment=f"не удалось прочитать ответ модели: {exc}", provider=self.name, searches=searches)
        return parse_lookup(payload, query=query, today=today, provider=self.name, searches=searches)


class FakePriceProvider:
    """Заглушка для разработки и показа интерфейса без ключа (PRICE_SEARCH_PROVIDER=fake):
    выдуманные предложения, везде помеченные как тестовые. Настоящих цен не даёт."""

    name = "fake"
    model = "тестовые данные"

    def lookup(self, name: str, description: str, unit: str, today: str) -> InternetLookup:
        import hashlib

        seed = int(hashlib.md5(normalize_name(name).encode("utf-8")).hexdigest()[:6], 16)  # noqa: S324 — не криптография
        base = float(500 + seed % 20000)
        offers = [
            InternetOffer(title=f"{name} (тестовые данные)", url="https://example.com/offer/1", shop="Тестовый магазин", price=base),
            InternetOffer(title=f"{name}, вариант (тестовые данные)", url="https://example.com/offer/2", shop="Другой тестовый магазин", price=round(base * 1.18, 2)),
            InternetOffer(title="Похожий товар (тестовые данные)", url="https://example.com/offer/3", shop="Тестовый маркетплейс", price=round(base * 0.9, 2), analog=True, note="аналог"),
        ]
        return InternetLookup(
            status="found",
            query=build_query(name, description),
            looked_up_at=today,
            offers=offers,
            price=base,
            comment="Тестовые данные: поиск в интернете не настроен, цены выдуманы.",
            provider=self.name,
        )


class InternetPriceService:
    """Поиск цен пачками с кэшем на диске. Без провайдера (нет ключа) — только отвечает,
    что не настроен."""

    def __init__(
        self,
        provider: PriceSearchProvider | None,
        data_dir: str | Path | None = None,
        ttl_days: int = DEFAULT_TTL_DAYS,
        concurrency: int = DEFAULT_CONCURRENCY,
    ):
        self.provider = provider
        self.data_dir = Path(data_dir or os.environ.get("DATA_DIR") or DEFAULT_DATA_DIR)
        self.path = self.data_dir / "internet_prices.json"
        self.ttl_days = ttl_days
        self.concurrency = max(1, concurrency)
        self._cache: dict[str, InternetLookup] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> InternetPriceService:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        provider: PriceSearchProvider | None = None
        if os.environ.get("PRICE_SEARCH_PROVIDER", "").strip().lower() == "fake":
            provider = FakePriceProvider()
        elif api_key:
            provider = ClaudeWebSearchProvider(
                api_key=api_key,
                model=os.environ.get("PRICE_SEARCH_MODEL", DEFAULT_MODEL),
                effort=os.environ.get("PRICE_SEARCH_EFFORT", DEFAULT_EFFORT),
                max_searches=int(os.environ.get("PRICE_SEARCH_MAX_SEARCHES", DEFAULT_MAX_SEARCHES)),
            )
        return cls(
            provider,
            ttl_days=int(os.environ.get("INTERNET_PRICE_TTL_DAYS", DEFAULT_TTL_DAYS)),
            concurrency=int(os.environ.get("INTERNET_PRICE_CONCURRENCY", DEFAULT_CONCURRENCY)),
        )

    @property
    def configured(self) -> bool:
        return self.provider is not None

    def info(self) -> InternetSearchInfo:
        return InternetSearchInfo(
            configured=self.configured,
            provider=self.provider.name if self.provider else "",
            model=self.provider.model if self.provider else "",
            cached=len(self._cache),
            ttl_days=self.ttl_days,
        )

    def load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        with self._lock:
            self._cache = {key: InternetLookup.model_validate(value) for key, value in raw.get("lookups", {}).items()}

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            payload = {"lookups": {key: value.model_dump() for key, value in self._cache.items()}}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def cache_key(name: str, description: str) -> str:
        return f"{normalize_name(name)}|{normalize_name(description)[:300]}"

    def cached(self, name: str, description: str, today: str | None = None) -> InternetLookup | None:
        """Свежая запись из кэша (не старше ttl_days) или None."""
        today = today or today_moscow()
        with self._lock:
            entry = self._cache.get(self.cache_key(name, description))
        if entry is None or not entry.looked_up_at:
            return None
        try:
            age = (date.fromisoformat(today) - date.fromisoformat(entry.looked_up_at)).days
        except ValueError:
            return None
        return entry if 0 <= age < self.ttl_days else None

    def lookup_many(self, items: list[MatchRequestItem], refresh: bool = False) -> dict[str, InternetLookup]:
        """id позиции → результат. Одинаковые позиции ищутся один раз; ошибки не кэшируются."""
        today = today_moscow()
        result: dict[str, InternetLookup] = {}
        pending: dict[str, MatchRequestItem] = {}
        waiting: dict[str, list[str]] = {}
        for item in items:
            key = self.cache_key(item.name, item.description)
            cached = None if refresh else self.cached(item.name, item.description, today)
            if cached is not None:
                result[item.id] = cached
                continue
            pending.setdefault(key, item)
            waiting.setdefault(key, []).append(item.id)
        if pending and self.provider is not None:
            keys = list(pending)
            with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                lookups = list(pool.map(lambda key: self._lookup_one(pending[key], today), keys))
            with self._lock:
                for key, lookup in zip(keys, lookups):
                    if lookup.status != "error":
                        self._cache[key] = lookup
            for key, lookup in zip(keys, lookups):
                for item_id in waiting[key]:
                    result[item_id] = lookup
            self.save()
        return result

    def _lookup_one(self, item: MatchRequestItem, today: str) -> InternetLookup:
        assert self.provider is not None
        try:
            return self.provider.lookup(item.name, item.description, getattr(item, "unit", "") or "", today)
        except Exception as exc:  # noqa: BLE001 — одна неудача не должна валить всю пачку
            return InternetLookup(
                status="error",
                query=build_query(item.name, item.description),
                looked_up_at=today,
                comment=str(exc)[:300],
                provider=self.provider.name,
            )
