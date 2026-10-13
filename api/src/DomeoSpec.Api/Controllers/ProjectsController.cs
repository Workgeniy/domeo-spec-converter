using DomeoSpec.Application.Common;
using DomeoSpec.Application.Quotations;
using DomeoSpec.Domain.Quotations;
using Microsoft.AspNetCore.Mvc;
namespace DomeoSpec.Api.Controllers;

[ApiController]
[Route("api/specifications/projects")]
public sealed class ProjectsController(IProjectStore store) : ControllerBase
{
    [HttpGet]
    public async Task<ActionResult<ApiResponse<IReadOnlyList<ProjectInfo>>>> List([FromQuery] string search = "",
        [FromQuery] int offset = 0, [FromQuery] int limit = 30, CancellationToken ct = default)
    {
        if (offset < 0 || limit is < 1 or > 100 || search.Length > 200)
            throw new ValidationFailedException("Некорректные параметры поиска.");
        return ApiResponse<IReadOnlyList<ProjectInfo>>.Ok(await store.ListProjectsAsync(search, offset, limit, ct));
    }
    [HttpGet("{id:guid}")]
    public async Task<ActionResult<ApiResponse<ProjectDetail>>> Get(Guid id, CancellationToken ct)
        => ApiResponse<ProjectDetail>.Ok(await store.GetProjectAsync(id, ct) ?? throw new NotFoundException("Объект не найден."));

    [HttpPut("{id:guid}")]
    [RequestSizeLimit(100L * 1024 * 1024)]
    public async Task<ActionResult<ApiResponse<ProjectInfo>>> Save(Guid id, SaveProject request,
        [FromServices] SaveProjectHandler handler, CancellationToken ct)
        => ApiResponse<ProjectInfo>.Ok(await handler.HandleAsync(id, request, ct));
}
