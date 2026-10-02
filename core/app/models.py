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


class HistoryCandidate(BaseModel):
    """Позиция прайса закупки, похожая на позицию спецификации."""

    key: str
    name: str
    group: str = ""
    score: float = 0.0  # 1.0 — точное совпадение наименования
    alias: str = ""  # совпало не с нашим наименованием, а с названием у поставщика из истории
    price_min: float | None = None
    price_max: float | None = None
    price_median: float | None = None
    price_last: float | None = None
    last_date: str | None = None
    purchases: int = 0
    descriptions: list[str] = Field(default_factory=list)


class HistoryPurchase(BaseModel):
    """Одна покупка из истории — чтобы оператор видел, откуда эталон."""

    purchased_at: str | None = None
    unit_price: float
    qty: float
    partner_item: str = ""
    order: str = ""
    outlier: bool = False


MatchKind = Literal["exact", "fuzzy", "analog", "none"]


class HistoryPrice(BaseModel):
    """Результат сопоставления позиции с историей закупок."""

    kind: MatchKind = "none"
    best: HistoryCandidate | None = None
    candidates: list[HistoryCandidate] = Field(default_factory=list)  # до 5 лучших, включая best
    purchases: list[HistoryPurchase] = Field(default_factory=list)  # последние покупки best
    matched_at: str = ""


class InternetOffer(BaseModel):
    """Одно предложение из интернета — чтобы оператор видел, где и почём нашлось."""

    title: str = ""
    url: str = ""
    shop: str = ""
    price: float  # за единицу, руб. с НДС
    analog: bool = False  # не та же позиция, а похожая
    note: str = ""


InternetStatus = Literal["found", "not_found", "error"]


class SearchParam(BaseModel):
    """Параметр поиска цены, который задал оператор: «Материал ножек: металл», «Цвет: серый»."""

    name: str = ""
    value: str = ""


class InternetLookup(BaseModel):
    """Результат поиска цены в интернете на дату."""

    status: InternetStatus = "not_found"
    query: str = ""
    looked_up_at: str = ""  # дата, на которую найдена цена (ГГГГ-ММ-ДД)
    offers: list[InternetOffer] = Field(default_factory=list)
    price: float | None = None  # рекомендуемая цена: типичная среди подходящих предложений
    comment: str = ""
    provider: str = ""
    searches: int = 0  # сколько поисковых запросов ушло (для оценки расходов)
    params: list[SearchParam] = Field(default_factory=list)  # с какими параметрами оператора искали


# Откуда взята базовая цена позиции: выбор оператора.
PriceSource = Literal["", "manual", "history_min", "history_max", "history_median", "history_last", "internet"]


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
    price: float | None = None  # базовая цена за единицу с НДС — выбранная оператором (см. price_source)
    price_source: PriceSource = ""
    history: HistoryPrice | None = None  # сопоставление с историей закупок
    internet: InternetLookup | None = None  # поиск в интернете: предложения и рекомендуемая цена
    internet_price: float | None = None  # цена из интернета на дату — выбранное предложение
    internet_source: str = ""  # ссылка на предложение
    internet_date: str = ""
    search_params: list[SearchParam] = Field(default_factory=list)  # параметры поиска цены от оператора: материал, цвет…
    # Подлежит монтажу/пусконаладке → лист «1» (Приложение №1.1, с графами СМР);
    # иначе инвентарь → лист «2» (Приложение №1.2).
    installation: bool = True
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
PageSource = Literal["text", "ocr", "skipped", "xlsx"]


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


class KpSettings(BaseModel):
    """Параметры КП — приложений к договору по образцу заказчика. Правила цены применяются
    поверх базовой цены строки (`SummaryItem.price` — закупочная или найденная, с НДС)."""

    contract_number: str = ""  # для шапки «Приложение №1.1 к Договору № … от …»
    contract_date: str = ""  # ДД.ММ.ГГГГ или ГГГГ-ММ-ДД
    supplier_position: str = "Генеральный директор"  # должность подписанта в блоке подписей
    customer_position: str = "Генеральный директор"
    vat_rate: float = 0.22  # 0 — без НДС
    markup_percent: float = 0.0  # наценка на базовую цену (графа-подсказка «пр» в образце)
    delivery_percent: float = 0.0  # доставка — входит в цену товара (графа «дост»)
    installation_percent: float = 0.0  # СМР от цены товара — только лист «1» (графа «монт»)
    round_to_ruble: bool = False  # цены в КП — до рубля, иначе до копейки


ExportKind = Literal["working", "kp", "cost"]


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
    kp: KpSettings | None = None
    # working — рабочая выгрузка; kp — приложения к договору; cost — себестоимость для Домео.
    # Не задано: kp, если есть параметры КП, иначе working (совместимость со старыми клиентами).
    kind: ExportKind | None = None
    indexation: "Indexation | None" = None  # цены к дате поставки (см. ниже)

    def resolved_kind(self) -> ExportKind:
        if self.kind:
            return self.kind
        return "kp" if self.kp is not None else "working"


# ---------- прайс закупки ----------


class PriceListInfo(BaseModel):
    """Сводка по загруженному прайсу закупки."""

    source: str = ""
    built_at: str = ""
    rows_total: int = 0
    entries: int = 0
    with_two_or_more: int = 0
    purchases: int = 0
    outliers: int = 0
    period_from: str | None = None
    period_to: str | None = None


class MatchRequestItem(BaseModel):
    id: str
    name: str
    description: str = ""
    unit: str = ""  # для поиска в интернете: цена нужна за эту единицу
    section: str = ""  # раздел КП: прайсы того же раздела чуть надёжнее
    search_params: list[SearchParam] = Field(default_factory=list)  # для поиска в интернете: материал, цвет… от оператора
    type_mark: str = ""  # графа «Тип, марка»: «по типу Polair CM107-S» — эталонная модель для поиска


class MatchRequest(BaseModel):
    items: list[MatchRequestItem] = Field(default_factory=list)


class MatchResponse(BaseModel):
    matches: dict[str, HistoryPrice] = Field(default_factory=dict)  # id позиции → результат


# ---------- цена из интернета ----------


class InternetSearchInfo(BaseModel):
    """Состояние поиска цен в интернете: настроен ли, чем ищем, сколько в кэше."""

    configured: bool = False
    provider: str = ""
    model: str = ""
    cached: int = 0
    ttl_days: int = 7


class InternetLookupRequest(BaseModel):
    items: list[MatchRequestItem] = Field(default_factory=list)
    refresh: bool = False  # искать заново, не глядя на кэш


class InternetLookupResponse(BaseModel):
    lookups: dict[str, InternetLookup] = Field(default_factory=dict)  # id позиции → результат


# ---------- каталоги поставщиков ----------

SupplierKind = Literal["site", "pricelist"]
SupplierStatus = Literal["idle", "running", "done", "error"]


class Supplier(BaseModel):
    """Поставщик, чьи цены собираем: сайт (обход каталога) и/или прайс-лист xlsx."""

    id: str
    name: str
    site: str = ""  # https://example.ru — обходим карту сайта, фид YML, разметку страниц
    kind: SupplierKind = "site"
    source: str = ""  # что нашли: адрес фида/карты сайта или имя файла прайса
    offers: int = 0
    collected_at: str = ""  # дата последнего сбора (ГГГГ-ММ-ДД)
    status: SupplierStatus = "idle"
    progress: str = ""  # «страниц 120 из 500, цен 80»
    error: str = ""
    max_pages: int = 3000
    discovered: bool = False  # найден автопоиском, а не заведён оператором
    query: str = ""  # по какому запросу нашёлся
    crawled: bool = False  # каталог обходили целиком (а не только страницы из поиска)
    sections: list[str] = Field(default_factory=list)  # разделы КП, которые закрывает поставщик


class SupplierOffer(BaseModel):
    """Одна позиция каталога поставщика."""

    supplier_id: str
    supplier: str
    name: str
    price: float  # за единицу, руб.
    url: str = ""
    sku: str = ""
    collected_at: str = ""
    section: str = ""  # раздел прайса, если загружали прайс по разделу


class SupplierCreate(BaseModel):
    name: str
    site: str = ""
    max_pages: int = 3000
    sections: list[str] = Field(default_factory=list)


class SupplierUpdate(BaseModel):
    name: str | None = None
    sections: list[str] | None = None
    max_pages: int | None = None


class SupplierIndexInfo(BaseModel):
    suppliers: list[Supplier] = Field(default_factory=list)
    offers: int = 0
    updated_at: str = ""
    autocrawl_pages: int = 300  # 0 — найденные автопоиском сайты не обходить
    min_shops: int = 3  # искать в интернете, пока по позиции меньше стольких магазинов
    queued: int = 0  # сколько сайтов ждёт обхода
    search_engine: str = ""  # чем ищем в интернете; пусто — автопоиск выключен


class SupplierSettings(BaseModel):
    autocrawl_pages: int = Field(default=300, ge=0, le=50_000)
    min_shops: int = Field(default=3, ge=1, le=10)


class SupplierSample(BaseModel):
    offers: list[SupplierOffer] = Field(default_factory=list)


# ---------- индексация цен к дате поставки ----------


class IndexationPair(BaseModel):
    """Изменение цен одних и тех же позиций между двумя годами."""

    years: str  # «2024→2025»
    rate: float  # % за год (медиана по позициям)
    samples: int  # сколько позиций сравнивалось


class IndexationGroup(BaseModel):
    group: str  # группа из истории закупок или «все группы»
    rate: float | None = None  # % в год по последним годам; None — данных мало
    samples: int = 0
    pairs: list[IndexationPair] = Field(default_factory=list)


class HistoryIndexation(BaseModel):
    """Рост цен по истории закупок: по группам и в целом."""

    overall: IndexationGroup | None = None
    groups: list[IndexationGroup] = Field(default_factory=list)
    computed_at: str = ""


IndexationSource = Literal["history", "supplier", "official", "manual"]


class IndexationRate(BaseModel):
    """Ставка индексации раздела, выбранная оператором."""

    section: str  # раздел КП; «» — для разделов без своей ставки
    rate: float = Field(ge=-50, le=200)  # % в год
    source: IndexationSource = "manual"
    note: str = ""  # откуда: «ответ поставщика от 12.10», «ИПЦ Росстат» и т. п.
    updated_at: str = ""


class IndexationRates(BaseModel):
    rates: list[IndexationRate] = Field(default_factory=list)


class IndexationInfo(BaseModel):
    history: HistoryIndexation | None = None  # None — история закупок не загружена
    rates: list[IndexationRate] = Field(default_factory=list)


class Indexation(BaseModel):
    """Индексация в выгрузке: дата поставки и ставки по разделам (ключ «» — по умолчанию)."""

    date: str = ""  # ГГГГ-ММ-ДД; пусто — без индексации
    rates: dict[str, float] = Field(default_factory=dict)
    apply_to_kp: bool = False  # считать КП от проиндексированной базовой цены
