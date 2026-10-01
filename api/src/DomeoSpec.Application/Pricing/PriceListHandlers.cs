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
        return await engine.AddSupplierAsync(new SupplierCreate(name, site, pages, Sections.Clean(body.Sections)), ct);
    }

    private static bool IsSite(string site)
    {
        var withScheme = site.Contains("://") ? site : "https://" + site;
        return Uri.TryCreate(withScheme, UriKind.Absolute, out var uri)
               && uri.Scheme is "http" or "https"
               && uri.Host.Contains('.');
    }
}

/// <summary>Разделы КП у поставщика и прайса: короткие названия без дублей.</summary>
public static class Sections
{
    public const int MaxLength = 60;
    public const int MaxCount = 30;

    public static IReadOnlyList<string> Clean(IReadOnlyList<string>? sections)
    {
        var result = new List<string>();
        foreach (var raw in sections ?? [])
        {
            var section = string.Join(' ', (raw ?? "").Split(' ', StringSplitOptions.RemoveEmptyEntries));
            if (section.Length == 0)
                continue;
            if (section.Length > MaxLength)
                throw new ValidationFailedException($"Название раздела длиннее {MaxLength} символов.");
            if (!result.Any(s => string.Equals(s, section, StringComparison.OrdinalIgnoreCase)))
                result.Add(section);
        }
        if (result.Count > MaxCount)
            throw new ValidationFailedException($"Разделов не больше {MaxCount}.");
        return result;
    }

    public static string CleanOne(string? section)
    {
        var cleaned = Clean(section is null ? null : [section]);
        return cleaned.Count == 0 ? "" : cleaned[0];
    }
}

/// <summary>Сценарий «изменить поставщика»: название, разделы, глубина обхода.</summary>
public sealed class UpdateSupplierHandler(IPricingEngine engine)
{
    public async Task<Supplier> HandleAsync(string id, SupplierUpdate body, CancellationToken ct)
    {
        string? name = null;
        if (body.Name is not null)
        {
            name = body.Name.Trim();
            if (name.Length == 0 || name.Length > AddSupplierHandler.MaxNameLength)
                throw new ValidationFailedException("Название поставщика — от 1 до 120 символов.");
        }
        var sections = body.Sections is null ? null : Sections.Clean(body.Sections);
        int? pages = body.MaxPages is null ? null : Math.Clamp(body.MaxPages.Value, 50, 50_000);
        return await engine.UpdateSupplierAsync(id, new SupplierUpdate(name, sections, pages), ct);
    }
}

/// <summary>Сценарий «загрузить прайс-лист поставщика» (весь или по разделу).</summary>
public sealed class UploadSupplierPriceListHandler(IPricingEngine engine)
{
    public async Task<Supplier> HandleAsync(string id, Stream xlsx, string fileName, long length, string? section, CancellationToken ct)
    {
        var ok = fileName.EndsWith(".xlsx", StringComparison.OrdinalIgnoreCase) || fileName.EndsWith(".xlsm", StringComparison.OrdinalIgnoreCase);
        if (string.IsNullOrWhiteSpace(fileName) || !ok)
            throw new ValidationFailedException("Ожидается прайс-лист в формате xlsx.");
        if (length <= 0)
            throw new ValidationFailedException("Файл пустой.");
        if (length > UploadPriceListHandler.MaxFileBytes)
            throw new ValidationFailedException("Файл больше 100 МБ.");
        return await engine.UploadSupplierPriceListAsync(id, xlsx, fileName, Sections.CleanOne(section), ct);
    }
}

/// <summary>Сценарий «сохранить ставки индексации по разделам».</summary>
public sealed class SetIndexationHandler(IPricingEngine engine)
{
    private static readonly HashSet<string> Sources = ["history", "supplier", "official", "manual"];

    public async Task<IndexationInfo> HandleAsync(IndexationRates body, CancellationToken ct)
    {
        var cleaned = new List<IndexationRate>();
        foreach (var rate in body.Rates ?? [])
        {
            if (rate.Rate is < -50 or > 200 || double.IsNaN(rate.Rate))
                throw new ValidationFailedException("Ставка индексации — от −50 до 200 % в год.");
            if (!Sources.Contains(rate.Source))
                throw new ValidationFailedException("Источник ставки: history, supplier, official или manual.");
            var section = Sections.CleanOne(rate.Section);
            if (cleaned.Any(r => string.Equals(r.Section, section, StringComparison.OrdinalIgnoreCase)))
                throw new ValidationFailedException($"Раздел «{section}» указан дважды.");
            cleaned.Add(rate with { Section = section, Note = (rate.Note ?? "").Trim() });
        }
        return await engine.SetIndexationAsync(new IndexationRates(cleaned), ct);
    }
}

/// <summary>Сценарий «найти цены в интернете»: пачка небольшая — на позицию уходят десятки секунд.</summary>
public sealed class LookupInternetHandler(IPricingEngine engine)
{
    public const int MaxItems = 50;
    public const int MaxParams = 10;
    public const int MaxParamName = 60;
    public const int MaxParamValue = 120;

    public async Task<IReadOnlyDictionary<string, InternetLookup>> HandleAsync(IReadOnlyList<MatchRequestItem> items, bool refresh, CancellationToken ct)
    {
        if (items.Count == 0)
            throw new ValidationFailedException("Нет позиций для поиска.");
        if (items.Count > MaxItems)
            throw new ValidationFailedException($"За один запрос ищем не больше {MaxItems} позиций.");
        if (items.Any(i => string.IsNullOrWhiteSpace(i.Id) || string.IsNullOrWhiteSpace(i.Name)))
            throw new ValidationFailedException("У каждой позиции должны быть id и наименование.");
        if (items.Any(i => i.SearchParams.Count > MaxParams))
            throw new ValidationFailedException($"У позиции не больше {MaxParams} параметров поиска.");
        if (items.SelectMany(i => i.SearchParams).Any(p => p.Name.Length > MaxParamName || p.Value.Length > MaxParamValue))
            throw new ValidationFailedException($"Параметр поиска: название — до {MaxParamName} символов, значение — до {MaxParamValue}.");
        return await engine.LookupInternetAsync(items, refresh, ct);
    }
}
