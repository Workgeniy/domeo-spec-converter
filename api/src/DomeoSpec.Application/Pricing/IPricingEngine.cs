using DomeoSpec.Domain.Specifications;

namespace DomeoSpec.Application.Pricing;

/// <summary>
/// Порт к прайсу закупки в ядре: загрузка выгрузки 1С, сводка, сопоставление позиций.
/// Прайс живёт в ядре (там же алгоритмы); api — единственный вход для фронта.
/// </summary>
public interface IPricingEngine
{
    /// <summary>Загрузить выгрузку 1С «Заказы поставщикам» и пересобрать прайс.</summary>
    Task<PriceListInfo> UploadPriceListAsync(Stream xlsx, string fileName, CancellationToken ct);

    /// <summary>Сводка по текущему прайсу; null — прайс ещё не загружен.</summary>
    Task<PriceListInfo?> GetPriceListAsync(CancellationToken ct);

    /// <summary>Сопоставить позиции с прайсом: id позиции → результат.</summary>
    Task<IReadOnlyDictionary<string, HistoryPrice>> MatchAsync(IReadOnlyList<MatchRequestItem> items, CancellationToken ct);

    /// <summary>Состояние поиска цен в интернете (настроен ли ключ, модель, размер кэша).</summary>
    Task<InternetSearchInfo> GetInternetSearchAsync(CancellationToken ct);

    /// <summary>Найти цены в интернете на дату: id позиции → результат. refresh — не глядя на кэш.</summary>
    Task<IReadOnlyDictionary<string, InternetLookup>> LookupInternetAsync(IReadOnlyList<MatchRequestItem> items, bool refresh, CancellationToken ct);

    // ---- каталоги поставщиков (индекс цен в ядре) ----

    Task<SupplierIndexInfo> GetSuppliersAsync(CancellationToken ct);

    Task<Supplier> AddSupplierAsync(SupplierCreate supplier, CancellationToken ct);

    Task RemoveSupplierAsync(string id, CancellationToken ct);

    /// <summary>Запустить обход сайта поставщика в фоне; состояние — в <see cref="GetSuppliersAsync"/>.</summary>
    Task<Supplier> StartCrawlAsync(string id, CancellationToken ct);

    Task<Supplier> StopCrawlAsync(string id, CancellationToken ct);

    /// <summary>Прайс-лист xlsx: с разделом заменяет цены только этого раздела, без — все цены поставщика.</summary>
    Task<Supplier> UploadSupplierPriceListAsync(string id, Stream xlsx, string fileName, string section, CancellationToken ct);

    Task<IReadOnlyList<SupplierOffer>> SampleOffersAsync(string id, CancellationToken ct);

    /// <summary>Название, разделы, глубина обхода поставщика.</summary>
    Task<Supplier> UpdateSupplierAsync(string id, SupplierUpdate update, CancellationToken ct);

    /// <summary>Настройки индекса: сколько страниц обходить у найденных автопоиском сайтов.</summary>
    Task<SupplierIndexInfo> UpdateSupplierSettingsAsync(SupplierSettings settings, CancellationToken ct);

    // ---- индексация цен к дате поставки ----

    /// <summary>Рост цен по истории закупок и ставки, выбранные оператором.</summary>
    Task<IndexationInfo> GetIndexationAsync(CancellationToken ct);

    /// <summary>Справочник ставок по разделам заменяется целиком.</summary>
    Task<IndexationInfo> SetIndexationAsync(IndexationRates rates, CancellationToken ct);
}
