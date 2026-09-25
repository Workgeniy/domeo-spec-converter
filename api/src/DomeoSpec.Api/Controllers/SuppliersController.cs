using DomeoSpec.Application.Common;
using DomeoSpec.Application.Pricing;
using DomeoSpec.Domain.Specifications;
using Microsoft.AspNetCore.Mvc;

namespace DomeoSpec.Api.Controllers;

/// <summary>Каталоги поставщиков: список, добавление, обход сайта, прайс-лист, примеры. Индекс живёт в ядре.
/// Под /api/specifications/, потому что на общем домене край отдаёт приложению только этот префикс.</summary>
[ApiController]
[Route("api/specifications/suppliers")]
public sealed class SuppliersController(IPricingEngine engine) : ControllerBase
{
    [HttpGet]
    public async Task<ActionResult<ApiResponse<SupplierIndexInfo>>> Get(CancellationToken ct)
    {
        return ApiResponse<SupplierIndexInfo>.Ok(await engine.GetSuppliersAsync(ct));
    }

    [HttpPost]
    public async Task<ActionResult<ApiResponse<Supplier>>> Add([FromBody] SupplierCreate body, [FromServices] AddSupplierHandler handler, CancellationToken ct)
    {
        return ApiResponse<Supplier>.Ok(await handler.HandleAsync(body, ct));
    }

    [HttpDelete("{id}")]
    public async Task<IActionResult> Remove(string id, CancellationToken ct)
    {
        await engine.RemoveSupplierAsync(id, ct);
        return NoContent();
    }

    /// <summary>Запустить обход сайта в фоне; прогресс виден в списке.</summary>
    [HttpPost("{id}/crawl")]
    public async Task<ActionResult<ApiResponse<Supplier>>> Crawl(string id, CancellationToken ct)
    {
        return ApiResponse<Supplier>.Ok(await engine.StartCrawlAsync(id, ct));
    }

    [HttpPost("{id}/stop")]
    public async Task<ActionResult<ApiResponse<Supplier>>> Stop(string id, CancellationToken ct)
    {
        return ApiResponse<Supplier>.Ok(await engine.StopCrawlAsync(id, ct));
    }

    /// <summary>Прайс-лист xlsx поставщика — заменяет его позиции в индексе.</summary>
    [HttpPost("{id}/pricelist")]
    [RequestSizeLimit(100L * 1024 * 1024)]
    public async Task<ActionResult<ApiResponse<Supplier>>> Upload(string id, IFormFile? file, [FromServices] UploadSupplierPriceListHandler handler, CancellationToken ct)
    {
        if (file is null)
            throw new ValidationFailedException("Не передан файл (поле form-data «file»).");
        await using var stream = file.OpenReadStream();
        return ApiResponse<Supplier>.Ok(await handler.HandleAsync(id, stream, file.FileName, file.Length, ct));
    }

    [HttpGet("{id}/sample")]
    public async Task<ActionResult<ApiResponse<SupplierSample>>> Sample(string id, CancellationToken ct)
    {
        return ApiResponse<SupplierSample>.Ok(new SupplierSample(await engine.SampleOffersAsync(id, ct)));
    }
}

public sealed record SupplierSample(IReadOnlyList<SupplierOffer> Offers);
