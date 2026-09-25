using DomeoSpec.Application.Common;
using DomeoSpec.Application.Pricing;
using DomeoSpec.Domain.Specifications;
using Microsoft.AspNetCore.Mvc;

namespace DomeoSpec.Api.Controllers;

/// <summary>Прайс закупки: история 1С → эталонные цены → сопоставление позиций. Всё под /api/specifications/,
/// потому что на общем домене край отдаёт приложению только этот префикс.</summary>
[ApiController]
[Route("api/specifications/pricelist")]
public sealed class PriceListController(IPricingEngine engine) : ControllerBase
{
    /// <summary>Сводка по загруженному прайсу; data = null, если прайса ещё нет.</summary>
    [HttpGet]
    public async Task<ActionResult<ApiResponse<PriceListInfo?>>> Get(CancellationToken ct)
    {
        return ApiResponse<PriceListInfo?>.Ok(await engine.GetPriceListAsync(ct));
    }

    /// <summary>Загрузить выгрузку 1С «Заказы поставщикам» (xlsx) — прайс пересобирается целиком.</summary>
    [HttpPost]
    [RequestSizeLimit(100L * 1024 * 1024)]
    public async Task<ActionResult<ApiResponse<PriceListInfo>>> Upload(IFormFile? file, [FromServices] UploadPriceListHandler handler, CancellationToken ct)
    {
        if (file is null)
            throw new ValidationFailedException("Не передан файл (поле form-data «file»).");
        await using var stream = file.OpenReadStream();
        return ApiResponse<PriceListInfo>.Ok(await handler.HandleAsync(stream, file.FileName, file.Length, ct));
    }

    /// <summary>Сопоставить позиции с историей закупок.</summary>
    [HttpPost("match")]
    public async Task<ActionResult<ApiResponse<MatchResult>>> Match([FromBody] MatchRequest request, [FromServices] MatchPriceListHandler handler, CancellationToken ct)
    {
        var matches = await handler.HandleAsync(request.Items, ct);
        return ApiResponse<MatchResult>.Ok(new MatchResult(matches));
    }
}

public sealed record MatchRequest(IReadOnlyList<MatchRequestItem> Items);

public sealed record MatchResult(IReadOnlyDictionary<string, HistoryPrice> Matches);
