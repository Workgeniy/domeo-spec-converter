namespace DomeoSpec.Application.Common;

/// <summary>
/// Машиночитаемые коды отказов — поле <c>code</c> в ProblemDetails у каждого ответа об ошибке.
/// Текст (<c>detail</c>, <c>title</c>) — для человека; логику клиент строит на коде.
/// Значения — часть контракта: не переименовывать, новые только добавлять.
/// </summary>
public static class ErrorCodes
{
    public const string ValidationFailed = "validation_failed";
    public const string NotFound = "not_found";
    /// <summary>422: ядро не смогло разобрать документ.</summary>
    public const string EngineFailed = "engine_failed";
    /// <summary>503: ядро разбора не отвечает — повторить позже (<c>Retry-After</c>).</summary>
    public const string ServiceUnavailable = "service_unavailable";
    public const string Unexpected = "unexpected";

    /// <summary>Код по HTTP-статусу — для ответов, которые формирует сам фреймворк (400 привязки модели, 404, 413…).</summary>
    public static string ForStatus(int? status) => status switch
    {
        400 or 413 or 415 => ValidationFailed,
        404 => NotFound,
        422 => EngineFailed,
        503 => ServiceUnavailable,
        _ => Unexpected,
    };
}
