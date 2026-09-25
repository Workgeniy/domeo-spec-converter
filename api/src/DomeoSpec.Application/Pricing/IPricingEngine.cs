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
}
