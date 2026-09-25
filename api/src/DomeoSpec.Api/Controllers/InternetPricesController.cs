using DomeoSpec.Application.Common;
using DomeoSpec.Application.Pricing;
using DomeoSpec.Domain.Specifications;
using Microsoft.AspNetCore.Mvc;

namespace DomeoSpec.Api.Controllers;

/// <summary>Цена из интернета на дату: состояние поиска и поиск пачкой. Под /api/specifications/,
/// потому что на общем домене край отдаёт приложению только этот префикс.</summary>
[ApiController]
[Route("api/specifications/internet")]
public sealed class InternetPricesController(IPricingEngine engine) : ControllerBase
{
    /// <summary>Настроен ли поиск (ключ на сервере ядра), какая модель, сколько позиций в кэше.</summary>
    [HttpGet]
    public async Task<ActionResult<ApiResponse<InternetSearchInfo>>> Get(CancellationToken ct)
    {
        return ApiResponse<InternetSearchInfo>.Ok(await engine.GetInternetSearchAsync(ct));
    }

    /// <summary>Найти цены для пачки позиций (до 50). refresh — искать заново, не глядя на кэш.</summary>
    [HttpPost("lookup")]
    public async Task<ActionResult<ApiResponse<InternetLookupResult>>> Lookup([FromBody] InternetLookupRequest request, [FromServices] LookupInternetHandler handler, CancellationToken ct)
    {
        var lookups = await handler.HandleAsync(request.Items, request.Refresh, ct);
        return ApiResponse<InternetLookupResult>.Ok(new InternetLookupResult(lookups));
    }
}

public sealed record InternetLookupRequest(IReadOnlyList<MatchRequestItem> Items, bool Refresh = false);

public sealed record InternetLookupResult(IReadOnlyDictionary<string, InternetLookup> Lookups);
