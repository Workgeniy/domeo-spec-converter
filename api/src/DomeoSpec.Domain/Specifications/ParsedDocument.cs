namespace DomeoSpec.Domain.Specifications;

/// <summary>
/// Разобранный том ТХ: страницы, строки спецификации как в PDF и свод по позициям.
/// Модель повторяет контракт ядра разбора (core/app/models.py); имена полей в JSON — snake_case.
/// </summary>
public sealed record ParsedDocument
{
    public string FileName { get; init; } = "";
    /// <summary>Шифр документа, например «ДОО350-ДОН-ПИР-П-ТХ1».</summary>
    public string DocCode { get; init; } = "";
    /// <summary>Наименование объекта.</summary>
    public string Title { get; init; } = "";
    /// <summary>Название спецификации («Спецификация технологического оборудования …»).</summary>
    public string SpecTitle { get; init; } = "";
    public IReadOnlyList<PageInfo> Pages { get; init; } = [];
    public IReadOnlyList<SpecItem> Items { get; init; } = [];
    public IReadOnlyList<SummaryItem> Summary { get; init; } = [];
    public IReadOnlyList<string> Warnings { get; init; } = [];
    /// <summary>Исходные PDF: один после разбора, несколько — когда фронт объединил тома одного объекта.</summary>
    public IReadOnlyList<SourceDocument> Documents { get; init; } = [];
    /// <summary>Параметры КП для выгрузки; null — просто спецификация без листа «КП».</summary>
    public KpSettings? Kp { get; init; }
    /// <summary>Вид выгрузки: working, kp или cost (себестоимость); null — kp при наличии параметров, иначе working.</summary>
    public string? Kind { get; init; }
}

/// <summary>Позиция прайса закупки, похожая на позицию спецификации.</summary>
public sealed record HistoryCandidate
{
    public string Key { get; init; } = "";
    public string Name { get; init; } = "";
    public string Group { get; init; } = "";
    /// <summary>1.0 — точное совпадение наименования.</summary>
    public double Score { get; init; }
    public double? PriceMin { get; init; }
    public double? PriceMax { get; init; }
    public double? PriceMedian { get; init; }
    public double? PriceLast { get; init; }
    public string? LastDate { get; init; }
    public int Purchases { get; init; }
    public IReadOnlyList<string> Descriptions { get; init; } = [];
}

/// <summary>Одна покупка из истории — чтобы оператор видел, откуда эталон.</summary>
public sealed record HistoryPurchase
{
    public string? PurchasedAt { get; init; }
    public double UnitPrice { get; init; }
    public double Qty { get; init; }
    public string PartnerItem { get; init; } = "";
    public string Order { get; init; } = "";
    public bool Outlier { get; init; }
}

/// <summary>Результат сопоставления позиции с историей закупок.</summary>
public sealed record HistoryPrice
{
    /// <summary>exact | fuzzy | analog | none.</summary>
    public string Kind { get; init; } = "none";
    public HistoryCandidate? Best { get; init; }
    public IReadOnlyList<HistoryCandidate> Candidates { get; init; } = [];
    public IReadOnlyList<HistoryPurchase> Purchases { get; init; } = [];
    public string MatchedAt { get; init; } = "";
}

/// <summary>Одно предложение из интернета — где и почём нашлось.</summary>
public sealed record InternetOffer
{
    public string Title { get; init; } = "";
    public string Url { get; init; } = "";
    public string Shop { get; init; } = "";
    /// <summary>За единицу, руб. с НДС.</summary>
    public double Price { get; init; }
    /// <summary>Не та же позиция, а похожая.</summary>
    public bool Analog { get; init; }
    public string Note { get; init; } = "";
}

/// <summary>Результат поиска цены в интернете на дату.</summary>
public sealed record InternetLookup
{
    /// <summary>found | not_found | error.</summary>
    public string Status { get; init; } = "not_found";
    public string Query { get; init; } = "";
    /// <summary>Дата, на которую найдена цена (ГГГГ-ММ-ДД).</summary>
    public string LookedUpAt { get; init; } = "";
    public IReadOnlyList<InternetOffer> Offers { get; init; } = [];
    /// <summary>Рекомендуемая цена — типичная среди подходящих предложений.</summary>
    public double? Price { get; init; }
    public string Comment { get; init; } = "";
    public string Provider { get; init; } = "";
    public int Searches { get; init; }
}

/// <summary>Сводка по загруженному прайсу закупки.</summary>
public sealed record PriceListInfo
{
    public string Source { get; init; } = "";
    public string BuiltAt { get; init; } = "";
    public int RowsTotal { get; init; }
    public int Entries { get; init; }
    public int WithTwoOrMore { get; init; }
    public int Purchases { get; init; }
    public int Outliers { get; init; }
    public string? PeriodFrom { get; init; }
    public string? PeriodTo { get; init; }
}

public sealed record MatchRequestItem(string Id, string Name, string Description = "", string Unit = "");

/// <summary>Состояние поиска цен в интернете: настроен ли, чем ищем (claude | suppliers | fake), сколько в кэше.</summary>
public sealed record InternetSearchInfo
{
    public bool Configured { get; init; }
    public string Provider { get; init; } = "";
    public string Model { get; init; } = "";
    public int Cached { get; init; }
    public int TtlDays { get; init; } = 7;
}

/// <summary>Поставщик, чьи цены собираем: сайт (обход каталога) и/или прайс-лист xlsx.</summary>
public sealed record Supplier
{
    public string Id { get; init; } = "";
    public string Name { get; init; } = "";
    public string Site { get; init; } = "";
    /// <summary>site | pricelist.</summary>
    public string Kind { get; init; } = "site";
    /// <summary>Что нашли: адрес фида/карты сайта или имя файла прайса.</summary>
    public string Source { get; init; } = "";
    public int Offers { get; init; }
    public string CollectedAt { get; init; } = "";
    /// <summary>idle | running | done | error.</summary>
    public string Status { get; init; } = "idle";
    public string Progress { get; init; } = "";
    public string Error { get; init; } = "";
    public int MaxPages { get; init; } = 3000;
    /// <summary>Найден автопоиском, а не заведён оператором.</summary>
    public bool Discovered { get; init; }
    /// <summary>По какому запросу нашёлся.</summary>
    public string Query { get; init; } = "";
    /// <summary>Каталог обходили целиком (а не только страницы из поиска).</summary>
    public bool Crawled { get; init; }
}

/// <summary>Одна позиция каталога поставщика.</summary>
public sealed record SupplierOffer
{
    public string SupplierId { get; init; } = "";
    public string Supplier { get; init; } = "";
    public string Name { get; init; } = "";
    public double Price { get; init; }
    public string Url { get; init; } = "";
    public string Sku { get; init; } = "";
    public string CollectedAt { get; init; } = "";
}

public sealed record SupplierCreate(string Name, string Site = "", int MaxPages = 3000);

public sealed record SupplierIndexInfo
{
    public IReadOnlyList<Supplier> Suppliers { get; init; } = [];
    public int Offers { get; init; }
    public string UpdatedAt { get; init; } = "";
    /// <summary>Сколько страниц обходить у сайтов, найденных автопоиском; 0 — не обходить.</summary>
    public int AutocrawlPages { get; init; } = 300;
    /// <summary>Искать в интернете, пока по позиции меньше стольких разных магазинов.</summary>
    public int MinShops { get; init; } = 3;
    public int Queued { get; init; }
    /// <summary>Чем ищем в интернете; пусто — автопоиск выключен.</summary>
    public string SearchEngine { get; init; } = "";
}

public sealed record SupplierSettings(int AutocrawlPages = 300, int MinShops = 3);

/// <summary>
/// Параметры КП — приложений к договору по образцу заказчика. Правила цены применяются поверх
/// базовой цены строки (<see cref="SummaryItem.Price"/>); сам расчёт живёт в ядре (core/app/export/kp.py).
/// </summary>
public sealed record KpSettings
{
    public string ContractNumber { get; init; } = "";
    public string ContractDate { get; init; } = "";
    public string SupplierPosition { get; init; } = "Генеральный директор";
    public string CustomerPosition { get; init; } = "Генеральный директор";
    public double VatRate { get; init; } = 0.2;
    public double MarkupPercent { get; init; }
    public double DeliveryPercent { get; init; }
    public double InstallationPercent { get; init; }
    public bool RoundToRuble { get; init; }
}

/// <summary>Сводка по одному исходному PDF.</summary>
public sealed record SourceDocument
{
    public string DocCode { get; init; } = "";
    public string FileName { get; init; } = "";
    public string Title { get; init; } = "";
    public string SpecTitle { get; init; } = "";
    public int PagesTotal { get; init; }
    public IReadOnlyList<int> SpecPages { get; init; } = [];
    public IReadOnlyList<int> OcrPages { get; init; } = [];
    public IReadOnlyList<int> SkippedPages { get; init; } = [];
    public int Rows { get; init; }
    public int Positions { get; init; }
    public IReadOnlyList<string> Warnings { get; init; } = [];
}

/// <summary>Одна строка спецификации в том виде, в каком она стоит в PDF.</summary>
public sealed record SpecItem
{
    public int Id { get; init; }
    public int Page { get; init; }
    /// <summary>Позиция как в документе: «2.10», «1,10б».</summary>
    public string Pos { get; init; } = "";
    /// <summary>Нормализованная позиция для группировки: «2.10», «1.10б».</summary>
    public string PosKey { get; init; } = "";
    /// <summary>Краткое наименование (первое предложение описания).</summary>
    public string Name { get; init; } = "";
    /// <summary>Полный текст графы «Наименование и техническая характеристика».</summary>
    public string Description { get; init; } = "";
    public string TypeMark { get; init; } = "";
    public string Code { get; init; } = "";
    public string Manufacturer { get; init; } = "";
    public string Unit { get; init; } = "";
    public double? Qty { get; init; }
    public string QtyRaw { get; init; } = "";
    public string Mass { get; init; } = "";
    public string Note { get; init; } = "";
    /// <summary>Помещение или раздел, к которому относится строка.</summary>
    public string Group { get; init; } = "";
    /// <summary>Шифр документа-источника.</summary>
    public string SourceDoc { get; init; } = "";
    public IReadOnlyList<string> Warnings { get; init; } = [];
}

/// <summary>Позиция, сведённая по всему документу (одна строка на позицию).</summary>
public sealed record SummaryItem
{
    public string Pos { get; init; } = "";
    public string PosKey { get; init; } = "";
    public string Name { get; init; } = "";
    public string Description { get; init; } = "";
    public string TypeMark { get; init; } = "";
    public string Manufacturer { get; init; } = "";
    public string Unit { get; init; } = "";
    public double? Qty { get; init; }
    /// <summary>«Раздел» в КП.</summary>
    public string Section { get; init; } = "";
    public string Note { get; init; } = "";
    /// <summary>Базовая цена за единицу с НДС — выбранная оператором (см. <see cref="PriceSource"/>); null — не проставлена.</summary>
    public double? Price { get; init; }
    /// <summary>Откуда взята цена: manual, history_min, history_max, history_median, history_last, internet или пусто.</summary>
    public string PriceSource { get; init; } = "";
    /// <summary>Сопоставление с историей закупок; null — ещё не сопоставляли.</summary>
    public HistoryPrice? History { get; init; }
    /// <summary>Поиск в интернете: предложения и рекомендуемая цена; null — ещё не искали.</summary>
    public InternetLookup? Internet { get; init; }
    /// <summary>Цена из интернета на дату — выбранное предложение.</summary>
    public double? InternetPrice { get; init; }
    public string InternetSource { get; init; } = "";
    public string InternetDate { get; init; } = "";
    /// <summary>Подлежит монтажу/пусконаладке → лист «1» (Приложение №1.1), иначе инвентарь → лист «2».</summary>
    public bool Installation { get; init; } = true;
    public string SourceDoc { get; init; } = "";
    public IReadOnlyList<GroupQty> Groups { get; init; } = [];
    public IReadOnlyList<int> ItemIds { get; init; } = [];
    public IReadOnlyList<string> Warnings { get; init; } = [];
}

public sealed record GroupQty
{
    public string Group { get; init; } = "";
    public double? Qty { get; init; }
}

public sealed record PageInfo
{
    public int Number { get; init; }
    /// <summary>spec | other.</summary>
    public string Kind { get; init; } = "other";
    /// <summary>text | ocr | skipped.</summary>
    public string Source { get; init; } = "text";
    public int Rows { get; init; }
    public IReadOnlyList<string> Warnings { get; init; } = [];
}
