using DomeoSpec.Application.Common;
using DomeoSpec.Application.Parsing;
using DomeoSpec.Domain.Specifications;
using Microsoft.AspNetCore.Mvc;

namespace DomeoSpec.Api.Controllers;

[ApiController]
[Route("api/specifications")]
public sealed class SpecificationsController : ControllerBase
{
    [HttpPost("check-drawing")]
    [RequestSizeLimit(100L * 1024 * 1024)]
    public async Task<ActionResult<ApiResponse<DrawingCheckResult>>> CheckDrawing(IFormFile? file,
        [FromForm] string pages, [FromForm] string items, [FromServices] CheckDrawingHandler handler, CancellationToken ct)
    {
        if (file is null) throw new ValidationFailedException("Не передан PDF-план.");
        IReadOnlyList<SummaryItem> rows;
        try
        {
            rows = System.Text.Json.JsonSerializer.Deserialize<SummaryItem[]>(items,
                new System.Text.Json.JsonSerializerOptions { PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.SnakeCaseLower }) ?? [];
        }
        catch (System.Text.Json.JsonException) { throw new ValidationFailedException("Некорректный список товаров."); }
        await using var stream = file.OpenReadStream();
        return ApiResponse<DrawingCheckResult>.Ok(await handler.HandleAsync(stream, file.FileName, file.Length, pages, rows, ct));
    }
    /// <summary>Разобрать PDF тома ТХ: строки спецификации, свод, замечания.</summary>
    [HttpPost("parse")]
    [RequestSizeLimit(100L * 1024 * 1024)]
    [ProducesResponseType(typeof(ApiResponse<ParsedDocument>), StatusCodes.Status200OK)]
    [ProducesResponseType(typeof(ProblemDetails), StatusCodes.Status400BadRequest)]
    [ProducesResponseType(typeof(ProblemDetails), StatusCodes.Status422UnprocessableEntity)]
    [ProducesResponseType(typeof(ProblemDetails), StatusCodes.Status503ServiceUnavailable)]
    public async Task<ActionResult<ApiResponse<ParsedDocument>>> Parse(IFormFile? file, [FromServices] ParseSpecificationHandler handler, CancellationToken ct)
    {
        if (file is null)
            throw new ValidationFailedException("Не передан файл (поле form-data «file»).");

        await using var stream = file.OpenReadStream();
        var document = await handler.HandleAsync(stream, file.FileName, file.Length, ct);
        return ApiResponse<ParsedDocument>.Ok(document);
    }

    /// <summary>Собрать Excel из разобранного (возможно, отредактированного на фронте) документа.</summary>
    [HttpPost("export")]
    [ProducesResponseType(typeof(FileContentResult), StatusCodes.Status200OK)]
    [ProducesResponseType(typeof(ProblemDetails), StatusCodes.Status400BadRequest)]
    [ProducesResponseType(typeof(ProblemDetails), StatusCodes.Status503ServiceUnavailable)]
    public async Task<IActionResult> Export([FromBody] ParsedDocument document, [FromServices] ExportSpecificationHandler handler, CancellationToken ct)
    {
        var file = await handler.HandleAsync(document, ct);
        return File(file.Content, file.ContentType, file.FileName);
    }
}

[ApiController]
public sealed class HealthController(IParsingEngine engine) : ControllerBase
{
    /// <summary>
    /// Состояние API и ядра разбора (доступность, OCR). Два адреса: короткий — для проб на
    /// стенде, под /api/specifications/ — для фронта: на общем домене под путём /spec/ край
    /// отдаёт приложению только /api/specifications/*, а /api/health там принадлежит другому сервису.
    /// </summary>
    [HttpGet("api/health")]
    [HttpGet("api/specifications/health")]
    public async Task<ActionResult<ApiResponse<HealthDto>>> Get(CancellationToken ct)
    {
        var engineHealth = await engine.GetHealthAsync(ct);
        return ApiResponse<HealthDto>.Ok(new HealthDto("ok", new EngineDto(engineHealth.Available, engineHealth.Ocr)));
    }
}

public sealed record HealthDto(string Status, EngineDto Engine);

public sealed record EngineDto(bool Available, string? Ocr);
