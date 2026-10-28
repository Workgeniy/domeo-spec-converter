from __future__ import annotations

from app.pricing.websearch import FallbackEngine, SearchHit


class Recorder:
    """Движок-заглушка: пишет запросы и отдаёт заданный хит либо кидает исключение."""

    def __init__(self, name: str, fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.calls: list[str] = []

    def search(self, query: str, max_results: int = 8) -> list[SearchHit]:
        self.calls.append(query)
        if self.fail:
            raise ConnectionError("движок недоступен")
        return [SearchHit(url=f"https://{self.name}.test/{query}")]


def test_fallback_uses_primary_when_it_works() -> None:
    primary, secondary = Recorder("searxng"), Recorder("ddgs")
    engine = FallbackEngine(primary, secondary)
    assert [h.url for h in engine.search("стол")] == ["https://searxng.test/стол"]
    assert primary.calls == ["стол"] and secondary.calls == []  # запасной не трогаем


def test_fallback_switches_to_secondary_on_failure_and_holds() -> None:
    primary, secondary = Recorder("searxng", fail=True), Recorder("ddgs")
    engine = FallbackEngine(primary, secondary, cooldown=100)
    # SearXNG упал — ответ берём у ddgs.
    assert [h.url for h in engine.search("q1")] == ["https://ddgs.test/q1"]
    assert primary.calls == ["q1"] and secondary.calls == ["q1"]
    # В пределах cooldown в недоступный SearXNG больше не бьёмся — сразу ddgs.
    engine.search("q2")
    assert primary.calls == ["q1"] and secondary.calls == ["q1", "q2"]
