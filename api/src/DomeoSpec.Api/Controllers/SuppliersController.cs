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

    /// <summary>Глубина обхода найденных автопоиском сайтов (0 — не обходить) и сколько магазинов по
    /// позиции считать достаточным, чтобы не ходить в интернет.</summary>
    [HttpPut("settings")]
    public async Task<ActionResult<ApiResponse<SupplierIndexInfo>>> Settings([FromBody] SupplierSettings body, CancellationToken ct)
    {
        if (body.AutocrawlPages is < 0 or > 50_000)
            throw new ValidationFailedException("Число страниц — от 0 до 50 000.");
        if (body.MinShops is < 1 or > 10)
            throw new ValidationFailedException("Число магазинов — от 1 до 10.");
        return ApiResponse<SupplierIndexInfo>.Ok(await engine.UpdateSupplierSettingsAsync(body, ct));
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

    /// <summary>Название, разделы КП и глубина обхода поставщика.</summary>
    [HttpPut("{id}")]
    public async Task<ActionResult<ApiResponse<Supplier>>> Update(string id, [FromBody] SupplierUpdate body, [FromServices] UpdateSupplierHandler handler, CancellationToken ct)
    {
        return ApiResponse<Supplier>.Ok(await handler.HandleAsync(id, body, ct));
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

    /// <summary>Прайс-лист xlsx поставщика: с полем «section» заменяет цены только этого раздела, без — все.</summary>
    [HttpPost("{id}/pricelist")]
    [RequestSizeLimit(100L * 1024 * 1024)]
    public async Task<ActionResult<ApiResponse<Supplier>>> Upload(string id, IFormFile? file, [FromForm] string? section, [FromServices] UploadSupplierPriceListHandler handler, CancellationToken ct)
    {
        if (file is null)
            throw new ValidationFailedException("Не передан файл (поле form-data «file»).");
        await using var stream = file.OpenReadStream();
        return ApiResponse<Supplier>.Ok(await handler.HandleAsync(id, stream, file.FileName, file.Length, section, ct));
    }

    [HttpGet("{id}/sample")]
    public async Task<ActionResult<ApiResponse<SupplierSample>>> Sample(string id, CancellationToken ct)
    {
        return ApiResponse<SupplierSample>.Ok(new SupplierSample(await engine.SampleOffersAsync(id, ct)));
    }
}

public sealed record SupplierSample(IReadOnlyList<SupplierOffer> Offers);
