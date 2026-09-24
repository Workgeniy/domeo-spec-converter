"""Модели данных: результат разбора спецификации и запрос на экспорт."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SpecItem(BaseModel):
    """Одна строка спецификации в том виде, в каком она стоит в PDF."""

    id: int
    page: int
    pos: str = ""  # позиция как в документе: «2.10», «1,10б»
    pos_key: str = ""  # нормализованная позиция для группировки: «2.10», «1.10б»
    name: str = ""  # краткое наименование (первое предложение описания)
    description: str = ""  # полный текст «Наименование и техническая характеристика»
    type_mark: str = ""  # «Тип, марка, обозначение документа»
    code: str = ""  # «Код изделия»
    manufacturer: str = ""  # «Завод-изготовитель»
    unit: str = ""
    qty: float | None = None
    qty_raw: str = ""
    mass: str = ""
    note: str = ""
    group: str = ""  # помещение или раздел, к которому относится строка
    warnings: list[str] = Field(default_factory=list)


class GroupQty(BaseModel):
    group: str
    qty: float | None = None


class SummaryItem(BaseModel):
    """Позиция, сведённая по всему документу (одна строка на позицию)."""

    pos: str = ""
    pos_key: str = ""
    name: str = ""
    description: str = ""
    type_mark: str = ""
    manufacturer: str = ""
    unit: str = ""
    qty: float | None = None
    section: str = ""  # «Раздел» в КП
    note: str = ""
    groups: list[GroupQty] = Field(default_factory=list)
    item_ids: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


PageKind = Literal["spec", "other"]
PageSource = Literal["text", "ocr", "skipped"]


class PageInfo(BaseModel):
    number: int
    kind: PageKind = "other"
    source: PageSource = "text"
    rows: int = 0
    warnings: list[str] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    file_name: str
    doc_code: str = ""  # шифр документа, например «ДОО350-ДОН-ПИР-П-ТХ1»
    title: str = ""  # наименование объекта
    spec_title: str = ""  # название спецификации («Спецификация технологического оборудования»)
    pages: list[PageInfo] = Field(default_factory=list)
    items: list[SpecItem] = Field(default_factory=list)
    summary: list[SummaryItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def spec_pages(self) -> list[PageInfo]:
        return [p for p in self.pages if p.kind == "spec"]


class ExportRequest(BaseModel):
    """Данные для формирования Excel. Фронт может прислать отредактированные строки."""

    file_name: str = "спецификация"
    doc_code: str = ""
    title: str = ""
    items: list[SpecItem] = Field(default_factory=list)
    summary: list[SummaryItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    pages: list[PageInfo] = Field(default_factory=list)
