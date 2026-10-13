using DomeoSpec.Application.Common;
using DomeoSpec.Application.Quotations;
using DomeoSpec.Domain.Quotations;
using Microsoft.AspNetCore.Mvc;
namespace DomeoSpec.Api.Controllers;

[ApiController]
[Route("api/specifications/quotations")]
public sealed class QuotationsController(IQuotationStore store) : ControllerBase
{
    [HttpGet]
    public async Task<ActionResult<ApiResponse<IReadOnlyList<QuotationInfo>>>> List([FromQuery] string search = "", [FromQuery] Guid? projectId = null,
        [FromQuery] int offset = 0, [FromQuery] int limit = 30, CancellationToken ct = default)
    {
        if (offset < 0 || limit is < 1 or > 100 || search.Length > 200) throw new ValidationFailedException("Некорректные параметры поиска.");
        return ApiResponse<IReadOnlyList<QuotationInfo>>.Ok(await store.ListAsync(search,projectId,offset,limit,ct));
    }
    [HttpPost]
    [RequestSizeLimit(100L * 1024 * 1024)]
    public async Task<ActionResult<ApiResponse<QuotationInfo>>> Save(SaveQuotation request, [FromServices] SaveQuotationHandler handler, CancellationToken ct)
        => ApiResponse<QuotationInfo>.Ok(await handler.HandleAsync(request,ct));
    [HttpGet("{id:guid}")]
    public async Task<ActionResult<ApiResponse<QuotationDetail>>> Get(Guid id, CancellationToken ct)
        => ApiResponse<QuotationDetail>.Ok(await store.GetAsync(id,ct) ?? throw new NotFoundException("КП не найдено."));
    [HttpGet("{id:guid}/file")]
    public async Task<IActionResult> Download(Guid id, CancellationToken ct)
    {
        var file = await store.GetFileAsync(id,ct) ?? throw new NotFoundException("КП не найдено.");
        return File(file.Content,file.ContentType,file.FileName);
    }
}
