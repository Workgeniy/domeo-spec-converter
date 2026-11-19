"""Хранение загруженного прайса закупки на стороне ядра.

Один прайс на сервис: файл ``pricelist.json`` в каталоге данных (переменная ``DATA_DIR``,
в контейнере — том /data). При старте подхватывается, при загрузке новой выгрузки —
пересобирается и заменяется; сопоставитель строится один раз на прайс.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ..models import HistoryPrice, MatchRequestItem, PriceListInfo
from .matching import Matcher
from .pricelist import PriceList, build_from_file, summary

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / ".data"


class PriceListStore:
    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir or os.environ.get("DATA_DIR") or DEFAULT_DATA_DIR)
        self.path = self.data_dir / "pricelist.json"
        self.price_list: PriceList | None = None
        self.matcher: Matcher | None = None

    def load(self) -> None:
        if self.path.exists():
            self._set(PriceList.load(self.path))

    def build_from_upload(self, content: bytes, file_name: str) -> PriceListInfo:
        suffix = Path(file_name).suffix or ".xlsx"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            price_list = build_from_file(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
        price_list.source = file_name
        self.data_dir.mkdir(parents=True, exist_ok=True)
        price_list.save(self.path)
        self._set(price_list)
        return self.info()  # type: ignore[return-value]

    def preview_from_upload(self, content: bytes, file_name: str) -> dict:
        """Разобрать выгрузку и вернуть сводку + примеры позиций БЕЗ сохранения — для предпросмотра."""
        suffix = Path(file_name).suffix or ".xlsx"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            price_list = build_from_file(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
        price_list.source = file_name
        data = summary(price_list)
        data["samples"] = [
            {
                "name": e.name,
                "group": e.group,
                "count": e.count,
                "price_min": e.price_min,
                "price_max": e.price_max,
                "price_median": e.price_median,
                "price_last": e.price_last,
                "last_date": e.last_date.isoformat() if e.last_date else None,
            }
            for e in price_list.entries  # все распознанные позиции — оператор листает в окне предпросмотра
        ]
        return data

    def info(self) -> PriceListInfo | None:
        return PriceListInfo(**summary(self.price_list)) if self.price_list else None

    def match(self, items: list[MatchRequestItem]) -> dict[str, HistoryPrice]:
        if self.matcher is None:
            return {}
        return {item.id: self.matcher.match(item.name, item.description) for item in items}

    def market_names(self, name: str, description: str = "") -> list[str]:
        """Как позицию называли поставщики по истории закупок — для поиска цен на рынке."""
        matcher = self.matcher
        return matcher.market_names(name, description) if matcher is not None else []

    def _set(self, price_list: PriceList) -> None:
        self.price_list = price_list
        self.matcher = Matcher(price_list)
