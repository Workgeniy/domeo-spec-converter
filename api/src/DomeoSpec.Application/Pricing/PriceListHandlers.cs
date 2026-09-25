using DomeoSpec.Application.Common;
using DomeoSpec.Domain.Specifications;

namespace DomeoSpec.Application.Pricing;

/// <summary>Сценарий «загрузить историю закупок»: проверка входа и вызов ядра.</summary>
public sealed class UploadPriceListHandler(IPricingEngine engine)
{
    public const long MaxFileBytes = 100L * 1024 * 1024;

    public async Task<PriceListInfo> HandleAsync(Stream xlsx, string fileName, long length, CancellationToken ct)
    {
        var ok = fileName.EndsWith(".xlsx", StringComparison.OrdinalIgnoreCase) || fileName.EndsWith(".xlsm", StringComparison.OrdinalIgnoreCase);
        if (string.IsNullOrWhiteSpace(fileName) || !ok)
            throw new ValidationFailedException("Ожидается выгрузка 1С в формате xlsx.");
        if (length <= 0)
            throw new ValidationFailedException("Файл пустой.");
        if (length > MaxFileBytes)
            throw new ValidationFailedException("Файл больше 100 МБ.");
        return await engine.UploadPriceListAsync(xlsx, fileName, ct);
    }
}

/// <summary>Сценарий «сопоставить позиции с историей закупок».</summary>
public sealed class MatchPriceListHandler(IPricingEngine engine)
{
    public const int MaxItems = 2000;

    public async Task<IReadOnlyDictionary<string, HistoryPrice>> HandleAsync(IReadOnlyList<MatchRequestItem> items, CancellationToken ct)
    {
        if (items.Count == 0)
            throw new ValidationFailedException("Нет позиций для сопоставления.");
        if (items.Count > MaxItems)
            throw new ValidationFailedException($"За один раз можно сопоставить не больше {MaxItems} позиций.");
        if (items.Any(i => string.IsNullOrWhiteSpace(i.Id) || string.IsNullOrWhiteSpace(i.Name)))
            throw new ValidationFailedException("У каждой позиции должны быть id и наименование.");
        return await engine.MatchAsync(items, ct);
    }
}

/// <summary>Сценарий «добавить поставщика»: название обязательно, сайт — если есть, то настоящий адрес.</summary>
public sealed class AddSupplierHandler(IPricingEngine engine)
{
    public const int MaxNameLength = 120;

    public async Task<Supplier> HandleAsync(SupplierCreate body, CancellationToken ct)
    {
        var name = (body.Name ?? "").Trim();
        if (name.Length == 0)
            throw new ValidationFailedException("Укажите название поставщика.");
        if (name.Length > MaxNameLength)
            throw new ValidationFailedException("Название поставщика слишком длинное.");
        var site = (body.Site ?? "").Trim();
        if (site.Length > 0 && !IsSite(site))
            throw new ValidationFailedException("Адрес сайта должен быть вида https://example.ru.");
        var pages = Math.Clamp(body.MaxPages <= 0 ? 3000 : body.MaxPages, 50, 50_000);
        return await engine.AddSupplierAsync(new SupplierCreate(name, site, pages), ct);
    }

    private static bool IsSite(string site)
    {
        var withScheme = site.Contains("://") ? site : "https://" + site;
        return Uri.TryCreate(withScheme, UriKind.Absolute, out var uri)
               && uri.Scheme is "http" or "https"
               && uri.Host.Contains('.');
    }
}

/// <summary>Сценарий «загрузить прайс-лист поставщика».</summary>
public sealed class UploadSupplierPriceListHandler(IPricingEngine engine)
{
    public async Task<Supplier> HandleAsync(string id, Stream xlsx, string fileName, long length, CancellationToken ct)
    {
        var ok = fileName.EndsWith(".xlsx", StringComparison.OrdinalIgnoreCase) || fileName.EndsWith(".xlsm", StringComparison.OrdinalIgnoreCase);
        if (string.IsNullOrWhiteSpace(fileName) || !ok)
            throw new ValidationFailedException("Ожидается прайс-лист в формате xlsx.");
        if (length <= 0)
            throw new ValidationFailedException("Файл пустой.");
        if (length > UploadPriceListHandler.MaxFileBytes)
            throw new ValidationFailedException("Файл больше 100 МБ.");
        return await engine.UploadSupplierPriceListAsync(id, xlsx, fileName, ct);
    }
}

/// <summary>Сценарий «найти цены в интернете»: пачка небольшая — на позицию уходят десятки секунд.</summary>
public sealed class LookupInternetHandler(IPricingEngine engine)
{
    public const int MaxItems = 50;

    public async Task<IReadOnlyDictionary<string, InternetLookup>> HandleAsync(IReadOnlyList<MatchRequestItem> items, bool refresh, CancellationToken ct)
    {
        if (items.Count == 0)
            throw new ValidationFailedException("Нет позиций для поиска.");
        if (items.Count > MaxItems)
            throw new ValidationFailedException($"За один запрос ищем не больше {MaxItems} позиций.");
        if (items.Any(i => string.IsNullOrWhiteSpace(i.Id) || string.IsNullOrWhiteSpace(i.Name)))
            throw new ValidationFailedException("У каждой позиции должны быть id и наименование.");
        return await engine.LookupInternetAsync(items, refresh, ct);
    }
}
