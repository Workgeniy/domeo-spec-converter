using DomeoSpec.Application.Common;
using DomeoSpec.Application.Parsing;
using DomeoSpec.Domain.Specifications;
using Microsoft.AspNetCore.Mvc;

namespace DomeoSpec.Api.Controllers;

[ApiController]
[Route("api/specifications")]
public sealed class SpecificationsController : ControllerBase
{
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
[Route("api/health")]
public sealed class HealthController(IParsingEngine engine) : ControllerBase
{
    /// <summary>Состояние API и ядра разбора (доступность, OCR).</summary>
    [HttpGet]
    public async Task<ActionResult<ApiResponse<HealthDto>>> Get(CancellationToken ct)
    {
        var engineHealth = await engine.GetHealthAsync(ct);
        return ApiResponse<HealthDto>.Ok(new HealthDto("ok", new EngineDto(engineHealth.Available, engineHealth.Ocr)));
    }
}

public sealed record HealthDto(string Status, EngineDto Engine);

public sealed record EngineDto(bool Available, string? Ocr);
