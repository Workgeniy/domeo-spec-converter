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
    source_doc: str = ""  # шифр документа-источника (важно, когда в выгрузке несколько томов)
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
    price: float | None = None  # цена за единицу с НДС — проставляется менеджером или этапом цен
    source_doc: str = ""
    groups: list[GroupQty] = Field(default_factory=list)
    item_ids: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SourceDocument(BaseModel):
    """Сводка по одному исходному PDF. В выгрузке из нескольких томов их несколько."""

    doc_code: str = ""
    file_name: str = ""
    title: str = ""
    spec_title: str = ""
    pages_total: int = 0
    spec_pages: list[int] = Field(default_factory=list)
    ocr_pages: list[int] = Field(default_factory=list)
    skipped_pages: list[int] = Field(default_factory=list)
    rows: int = 0
    positions: int = 0
    warnings: list[str] = Field(default_factory=list)  # замечания документа и страниц


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
    documents: list[SourceDocument] = Field(default_factory=list)  # один элемент после разбора

    @property
    def spec_pages(self) -> list[PageInfo]:
        return [p for p in self.pages if p.kind == "spec"]

    def source_summary(self) -> SourceDocument:
        return SourceDocument(
            doc_code=self.doc_code,
            file_name=self.file_name,
            title=self.title,
            spec_title=self.spec_title,
            pages_total=len(self.pages),
            spec_pages=[p.number for p in self.pages if p.kind == "spec"],
            ocr_pages=[p.number for p in self.pages if p.source == "ocr"],
            skipped_pages=[p.number for p in self.pages if p.source == "skipped"],
            rows=len(self.items),
            positions=len(self.summary),
            warnings=list(self.warnings) + [f"стр. {p.number}: {w}" for p in self.pages for w in p.warnings],
        )


class Party(BaseModel):
    """Сторона КП: поставщик или заказчик. Как в блоке подписей образца:
    должность жирным, организация жирным, на строке подписи — инициалы и фамилия."""

    name: str = ""  # ООО «…»
    position: str = "Генеральный директор"  # должность подписанта
    signatory: str = ""  # инициалы и фамилия для строки подписи: «Г.Д. Ходосок»
    contacts: str = ""  # телефон, почта — свободный текст


class KpSettings(BaseModel):
    """Параметры коммерческого предложения. Правила цены применяются поверх базовой цены строки
    (`SummaryItem.price` — закупочная или найденная, с НДС)."""

    number: str = ""
    date: str = ""  # ДД.ММ.ГГГГ или ГГГГ-ММ-ДД
    valid_days: int = 30  # срок действия предложения
    supplier: Party = Field(default_factory=Party)
    customer: Party = Field(default_factory=Party)
    contract_number: str = ""  # для шапки «Приложение №1.1 к Договору № … от …»
    contract_date: str = ""
    vat_rate: float = 0.2  # 0 — без НДС
    markup_percent: float = 0.0  # наценка на базовую цену
    installation_percent: float = 0.0  # СМР (монтаж/пусконаладка) от цены товара, графа K
    delivery_percent: float = 0.0  # доставка от стоимости товара — отдельной строкой в итогах
    round_to_ruble: bool = False  # цены в КП — до рубля, иначе до копейки
    terms: str = ""  # условия: срок поставки, оплата, гарантия


class ExportRequest(BaseModel):
    """Данные для формирования Excel. Фронт может прислать отредактированные строки,
    в том числе объединённые из нескольких томов одного объекта."""

    file_name: str = "спецификация"
    doc_code: str = ""
    title: str = ""
    items: list[SpecItem] = Field(default_factory=list)
    summary: list[SummaryItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    pages: list[PageInfo] = Field(default_factory=list)
    documents: list[SourceDocument] = Field(default_factory=list)
    kp: KpSettings | None = None  # без параметров — просто спецификация без листа «КП»
