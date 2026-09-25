using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using DomeoSpec.Application.Common;
using DomeoSpec.Application.Pricing;
using DomeoSpec.Domain.Specifications;

namespace DomeoSpec.Infrastructure.Engine;

/// <summary>Реализация <see cref="IPricingEngine"/> поверх HTTP API ядра (core/app/main.py, /api/pricelist*).</summary>
public sealed class PythonPricingClient(HttpClient http) : IPricingEngine
{
    private static readonly JsonSerializerOptions Json = PythonEngineClient.Json;

    public async Task<PriceListInfo> UploadPriceListAsync(Stream xlsx, string fileName, CancellationToken ct)
    {
        using var form = new MultipartFormDataContent();
        var file = new StreamContent(xlsx);
        file.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
        form.Add(file, "file", "history.xlsx");
        form.Add(new StringContent(fileName), "file_name");
        using var response = await SendAsync(() => http.PostAsync("/api/pricelist", form, ct), ct);
        return await response.Content.ReadFromJsonAsync<PriceListInfo>(Json, ct)
               ?? throw new ServiceUnavailableException("Ядро вернуло пустой ответ на загрузку прайса.");
    }

    public async Task<PriceListInfo?> GetPriceListAsync(CancellationToken ct)
    {
        HttpResponseMessage response;
        try
        {
            response = await http.GetAsync("/api/pricelist", ct);
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
        {
            throw new ServiceUnavailableException("Ядро разбора недоступно.", e);
        }
        using (response)
        {
            if (response.StatusCode == HttpStatusCode.NotFound)
                return null;
            if (!response.IsSuccessStatusCode)
                throw new ServiceUnavailableException($"Ядро ответило {(int)response.StatusCode} на запрос прайса.");
            return await response.Content.ReadFromJsonAsync<PriceListInfo>(Json, ct);
        }
    }

    public async Task<IReadOnlyDictionary<string, HistoryPrice>> MatchAsync(IReadOnlyList<MatchRequestItem> items, CancellationToken ct)
    {
        using var response = await SendAsync(() => http.PostAsJsonAsync("/api/pricelist/match", new { items }, Json, ct), ct);
        var body = await response.Content.ReadFromJsonAsync<MatchBody>(Json, ct);
        return body?.Matches ?? new Dictionary<string, HistoryPrice>();
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

        string? detail = null;
        try
        {
            detail = (await response.Content.ReadFromJsonAsync<ErrorBody>(Json, ct))?.Detail;
        }
        catch (JsonException)
        {
            // не JSON — оставим без подробностей
        }
        var status = response.StatusCode;
        response.Dispose();
        // 409 у ядра — «прайс не загружен»: это правило предметной области, а не сбой.
        if (status is HttpStatusCode.Conflict)
            throw new ValidationFailedException(detail ?? "Прайс закупки ещё не загружен.");
        if (status is HttpStatusCode.UnprocessableEntity or HttpStatusCode.BadRequest)
            throw new EngineFailureException(detail ?? "Ядро не смогло обработать выгрузку.");
        throw new ServiceUnavailableException($"Ядро разбора ответило {(int)status}: {detail}");
    }

    private sealed record MatchBody(Dictionary<string, HistoryPrice> Matches);

    private sealed record ErrorBody(string? Detail);
}
