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
        if (string.IsNullOrWhiteSpace(fileName) || !Supported.Any(ext => fileName.EndsWith(ext, StringComparison.OrdinalIgnoreCase)))
            throw new ValidationFailedException("Ожидается файл PDF или Excel (xlsx).");
        if (length <= 0)
            throw new ValidationFailedException("Файл пустой.");
        if (length > MaxFileBytes)
            throw new ValidationFailedException("Файл больше 100 МБ.");

        return await engine.ParseAsync(file, fileName, ct);
    }
}

/// <summary>Сценарий «собрать Excel»: на вход идёт разобранный (возможно, отредактированный) документ.</summary>
public sealed class ExportSpecificationHandler(IParsingEngine engine)
{
    public async Task<ExportedFile> HandleAsync(ParsedDocument document, CancellationToken ct)
    {
        if (document.Summary.Count == 0 && document.Items.Count == 0)
            throw new ValidationFailedException("Нечего выгружать: в документе нет строк спецификации.");

        return await engine.ExportAsync(document, ct);
    }
}
