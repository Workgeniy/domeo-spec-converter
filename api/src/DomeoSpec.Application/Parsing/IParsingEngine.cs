using DomeoSpec.Domain.Specifications;

namespace DomeoSpec.Application.Parsing;

/// <summary>
/// Порт к ядру разбора (Python-сервис в <c>core/</c>). Сценарии зависят от порта, а не от
/// HTTP-клиента: ядро можно заменить (другой процесс, in-process) сменой одной регистрации.
/// </summary>
public interface IParsingEngine
{
    Task<ParsedDocument> ParseAsync(Stream pdf, string fileName, CancellationToken ct);

    Task<ExportedFile> ExportAsync(ParsedDocument document, CancellationToken ct);

    Task<EngineHealth> GetHealthAsync(CancellationToken ct);
    Task<DrawingText> ExtractDrawingTextAsync(Stream pdf, string pages, CancellationToken ct)
        => throw new NotSupportedException();
}

public sealed record ExportedFile(byte[] Content, string FileName, string ContentType);

/// <summary>Состояние ядра: доступно ли и каким OCR умеет читать сканы (null — OCR не установлен).</summary>
public sealed record EngineHealth(bool Available, string? Ocr);
