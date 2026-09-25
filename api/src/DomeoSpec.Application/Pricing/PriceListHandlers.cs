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
