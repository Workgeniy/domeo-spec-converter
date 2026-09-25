"""Бесплатный веб-поиск для автопоиска поставщиков.

Движок — за протоколом ``SearchEngine``: ``DdgsEngine`` (библиотека ddgs: DuckDuckGo, Bing,
Яндекс и другие без ключей; режим ``auto`` сам перебирает источники) или свой SearXNG
(``SEARXNG_URL``). Запросы к поисковику идут не чаще одного раза в полторы секунды на
весь сервис — иначе бесплатные движки начинают отвечать капчей.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

MIN_INTERVAL = 1.5
_throttle_lock = threading.Lock()
_last_request = [0.0]


@dataclass
class SearchHit:
    url: str
    title: str = ""
    snippet: str = ""


class SearchEngine(Protocol):
    name: str

    def search(self, query: str, max_results: int = 8) -> list[SearchHit]: ...


def _throttle() -> None:
    with _throttle_lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()


class DdgsEngine:
    """Поиск через библиотеку ddgs (DuckDuckGo и другие движки, без ключа и оплаты)."""

    def __init__(self, backend: str = "auto", region: str = "ru-ru"):
        from ddgs import DDGS  # ленивый импорт: без автопоиска библиотека не нужна

        self._ddgs = DDGS
        self.backend = backend
        self.region = region
        self.name = f"ddgs/{backend}"

    FALLBACK_BACKENDS = ("duckduckgo", "bing")

    def search(self, query: str, max_results: int = 8) -> list[SearchHit]:
        # Один из бесплатных источников может не ответить — пробуем следующий, а не роняем позицию.
        backends = [self.backend] + [b for b in self.FALLBACK_BACKENDS if b != self.backend]
        last_error: Exception | None = None
        for backend in backends:
            _throttle()
            try:
                rows = self._ddgs().text(query, region=self.region, safesearch="off", max_results=max_results, backend=backend)
            except Exception as exc:  # noqa: BLE001 — библиотека кидает свои типы исключений
                last_error = exc
                continue
            hits: list[SearchHit] = []
            for row in rows or []:
                url = row.get("href") or row.get("url") or ""
                if url:
                    hits.append(SearchHit(url=url, title=row.get("title") or "", snippet=row.get("body") or ""))
            return hits
        raise RuntimeError(f"поисковик не ответил: {str(last_error)[:120]}")


class SearxngEngine:
    """Свой метапоиск SearXNG (JSON API) — если стоит на стенде."""

    name = "searxng"

    def __init__(self, base_url: str, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=20.0)

    def search(self, query: str, max_results: int = 8) -> list[SearchHit]:
        _throttle()
        response = self.client.get(f"{self.base_url}/search", params={"q": query, "format": "json", "language": "ru-RU", "categories": "general"})
        response.raise_for_status()
        results = response.json().get("results", [])
        return [SearchHit(url=r["url"], title=r.get("title", ""), snippet=r.get("content", "")) for r in results[:max_results] if r.get("url")]


def engine_from_env() -> SearchEngine | None:
    """WEB_SEARCH_ENGINE: off | searxng | ddgs; по умолчанию SearXNG, если задан SEARXNG_URL, иначе ddgs."""
    choice = os.environ.get("WEB_SEARCH_ENGINE", "").strip().lower()
    if choice == "off":
        return None
    searxng = os.environ.get("SEARXNG_URL", "").strip()
    if searxng and choice in ("", "searxng"):
        return SearxngEngine(searxng)
    if choice in ("", "ddgs"):
        try:
            return DdgsEngine(backend=os.environ.get("WEB_SEARCH_BACKEND", "auto").strip() or "auto")
        except ImportError:
            return None
    return None
