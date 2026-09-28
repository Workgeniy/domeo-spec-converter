using DomeoSpec.Application.Common;
using DomeoSpec.Application.Pricing;
using DomeoSpec.Domain.Specifications;
using Microsoft.AspNetCore.Mvc;

namespace DomeoSpec.Api.Controllers;

/// <summary>Индексация цен к дате поставки: рост цен по истории закупок (считает ядро) и ставки по
/// разделам, выбранные оператором. Под /api/specifications/, как и остальные ручки приложения.</summary>
[ApiController]
[Route("api/specifications/indexation")]
public sealed class IndexationController(IPricingEngine engine) : ControllerBase
{
    [HttpGet]
    public async Task<ActionResult<ApiResponse<IndexationInfo>>> Get(CancellationToken ct)
    {
        return ApiResponse<IndexationInfo>.Ok(await engine.GetIndexationAsync(ct));
    }

    /// <summary>Справочник ставок заменяется целиком тем, что прислал интерфейс.</summary>
    [HttpPut]
    public async Task<ActionResult<ApiResponse<IndexationInfo>>> Put([FromBody] IndexationRates body, [FromServices] SetIndexationHandler handler, CancellationToken ct)
    {
        return ApiResponse<IndexationInfo>.Ok(await handler.HandleAsync(body, ct));
    }
}
