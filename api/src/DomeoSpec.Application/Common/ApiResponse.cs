namespace DomeoSpec.Application.Common;

/// <summary>
/// Единый конверт успешного ответа: { success, data, message, errors } — тот же, что в остальных
/// сервисах Domeo. Ошибки уходят как RFC 7807 ProblemDetails.
/// <para>Отдельного проекта Contracts пока нет (швов между процессами внутри .NET-части ещё нет);
/// когда появится — конверт переезжает туда.</para>
/// </summary>
public sealed class ApiResponse<T>
{
    public bool Success { get; init; } = true;
    public T? Data { get; init; }
    public string? Message { get; init; }
    public IReadOnlyList<string> Errors { get; init; } = [];

    public static ApiResponse<T> Ok(T data, string? message = null) =>
        new() { Success = true, Data = data, Message = message };
}
