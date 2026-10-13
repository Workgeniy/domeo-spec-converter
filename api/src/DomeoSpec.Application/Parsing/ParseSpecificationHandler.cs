using DomeoSpec.Application.Common;
using DomeoSpec.Domain.Specifications;

namespace DomeoSpec.Application.Parsing;

/// <summary>Сценарий «разобрать том ТХ»: проверка входа и вызов ядра. Принимаем PDF и Excel
/// (xlsx/xlsm) — файл спецификации от проектировщика может быть и таблицей.</summary>
public sealed class ParseSpecificationHandler(IParsingEngine engine)
{
    public const long MaxFileBytes = 100L * 1024 * 1024;
    private static readonly string[] Supported = [".pdf", ".xlsx", ".xlsm"];

    public async Task<ParsedDocument> HandleAsync(Stream file, string fileName, long length, CancellationToken ct)
    {
        Validate(fileName, length);
        return await engine.ParseAsync(file, fileName, ct);
    }

    public static void Validate(string fileName, long length)
    {
        if (string.IsNullOrWhiteSpace(fileName) || !Supported.Any(ext => fileName.EndsWith(ext, StringComparison.OrdinalIgnoreCase)))
            throw new ValidationFailedException("Ожидается файл PDF или Excel (xlsx).");
        if (length <= 0)
            throw new ValidationFailedException("Файл пустой.");
        if (length > MaxFileBytes)
            throw new ValidationFailedException("Файл больше 100 МБ.");

    }
}

/// <summary>Сценарий «собрать Excel»: на вход идёт разобранный (возможно, отредактированный) документ.</summary>
public sealed class ExportSpecificationHandler(IParsingEngine engine)
{
    public async Task<ExportedFile> HandleAsync(ParsedDocument document, CancellationToken ct)
    {
        if (document.Summary.Count == 0 && document.Items.Count == 0)
            throw new ValidationFailedException("Нечего выгружать: в документе нет строк спецификации.");

        if (document.Kp is { } kp)
        {
            if (kp.MarginPercent is { } margin && (!double.IsFinite(margin) || margin < 0 || margin > 99.99))
                throw new ValidationFailedException("Маржа должна быть от 0 до 99,99%.");
            if (!double.IsFinite(kp.MarkupPercent) || kp.MarkupPercent < -100 ||
                !double.IsFinite(kp.DeliveryPercent) || kp.DeliveryPercent < 0 ||
                !double.IsFinite(kp.InstallationPercent) || kp.InstallationPercent < 0 ||
                !double.IsFinite(kp.VatRate) || kp.VatRate < 0)
                throw new ValidationFailedException("Некорректные проценты расчёта КП.");
        }
        if (document.Indexation is { BaseDate.Length: > 0 } ix &&
            !DateOnly.TryParseExact(ix.BaseDate, "yyyy-MM-dd", out _))
            throw new ValidationFailedException("Некорректная дата расчёта индексации.");
        return await engine.ExportAsync(document, ct);
    }
}
