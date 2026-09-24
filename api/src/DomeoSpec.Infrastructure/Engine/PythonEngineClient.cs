using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using DomeoSpec.Application.Common;
using DomeoSpec.Application.Parsing;
using DomeoSpec.Domain.Specifications;

namespace DomeoSpec.Infrastructure.Engine;

/// <summary>
/// Реализация порта <see cref="IParsingEngine"/> поверх HTTP API Python-ядра (core/app/main.py).
/// Коды ответа ядра различаются: 422 — документ не разобрать (повтор не поможет), всё прочее
/// и обрыв соединения — 503 для вызывающего.
/// </summary>
public sealed class PythonEngineClient(HttpClient http) : IParsingEngine
{
    public static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DictionaryKeyPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    public async Task<ParsedDocument> ParseAsync(Stream pdf, string fileName, CancellationToken ct)
    {
        // Кириллица в заголовке multipart у HttpClient кодируется так, что ядро её не читает,
        // поэтому файл уходит под ASCII-именем, а настоящее имя — отдельным полем формы.
        using var form = new MultipartFormDataContent();
        var file = new StreamContent(pdf);
        file.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
        form.Add(file, "file", "document.pdf");
        form.Add(new StringContent(fileName), "file_name");

        using var response = await SendAsync(() => http.PostAsync("/api/parse", form, ct), ct);
        return await response.Content.ReadFromJsonAsync<ParsedDocument>(Json, ct)
               ?? throw new ServiceUnavailableException("Ядро разбора вернуло пустой ответ.");
    }

    public async Task<ExportedFile> ExportAsync(ParsedDocument document, CancellationToken ct)
    {
        using var response = await SendAsync(() => http.PostAsJsonAsync("/api/export", document, Json, ct), ct);
        var bytes = await response.Content.ReadAsByteArrayAsync(ct);
        var name = response.Content.Headers.ContentDisposition?.FileNameStar
                   ?? response.Content.Headers.ContentDisposition?.FileName?.Trim('"')
                   ?? Path.ChangeExtension(document.FileName, ".xlsx");
        var type = response.Content.Headers.ContentType?.MediaType
                   ?? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
        return new ExportedFile(bytes, name, type);
    }

    public async Task<EngineHealth> GetHealthAsync(CancellationToken ct)
    {
        try
        {
            using var response = await http.GetAsync("/api/health", ct);
            if (!response.IsSuccessStatusCode)
                return new EngineHealth(false, null);
            var body = await response.Content.ReadFromJsonAsync<HealthBody>(Json, ct);
            return new EngineHealth(body?.Status == "ok", body?.Ocr);
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
        {
            return new EngineHealth(false, null);
        }
    }

    private static async Task<HttpResponseMessage> SendAsync(Func<Task<HttpResponseMessage>> send, CancellationToken ct)
    {
        HttpResponseMessage response;
        try
        {
            response = await send();
        }
        catch (HttpRequestException e)
        {
            throw new ServiceUnavailableException("Ядро разбора недоступно.", e);
        }
        catch (TaskCanceledException e) when (!ct.IsCancellationRequested)
        {
            throw new ServiceUnavailableException("Ядро разбора не ответило вовремя.", e);
        }

        if (response.IsSuccessStatusCode)
            return response;

        var detail = await ReadDetailAsync(response, ct);
        response.Dispose();
        if (response.StatusCode is HttpStatusCode.UnprocessableEntity or HttpStatusCode.BadRequest)
            throw new EngineFailureException(detail ?? "Ядро не смогло разобрать документ.");
        throw new ServiceUnavailableException($"Ядро разбора ответило {(int)response.StatusCode}: {detail}");
    }

    private static async Task<string?> ReadDetailAsync(HttpResponseMessage response, CancellationToken ct)
    {
        try
        {
            var body = await response.Content.ReadFromJsonAsync<ErrorBody>(Json, ct);
            return body?.Detail;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private sealed record HealthBody(string? Status, string? Ocr);

    private sealed record ErrorBody(string? Detail);
}
