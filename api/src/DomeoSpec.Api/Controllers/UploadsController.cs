using DomeoSpec.Application.Common;
using DomeoSpec.Application.Uploads;
using DomeoSpec.Domain.Uploads;
using Microsoft.AspNetCore.Mvc;
namespace DomeoSpec.Api.Controllers;
[ApiController]
[Route("api/specifications/uploads")]
public sealed class UploadsController(IUploadStore store) : ControllerBase
{
    [HttpPost]
    [RequestSizeLimit(101L * 1024 * 1024)]
    [RequestFormLimits(MultipartBodyLengthLimit=101L * 1024 * 1024)]
    public async Task<ActionResult<ApiResponse<UploadInfo>>> Save(IFormFile? file, [FromForm] Guid projectId,
        [FromServices] SaveUploadHandler handler, CancellationToken ct, [FromForm] string title="")
    {
        if (file is null) throw new ValidationFailedException("Не передан исходный файл.");
        await using var stream=file.OpenReadStream();
        return ApiResponse<UploadInfo>.Ok(await handler.HandleAsync(stream,file.FileName,file.Length,projectId,title,ct));
    }
    [HttpGet]
    public async Task<ActionResult<ApiResponse<IReadOnlyList<UploadInfo>>>> List([FromQuery] string search="", [FromQuery] int offset=0,
        [FromQuery] int limit=30, CancellationToken ct=default)
    {
        if(offset<0 || limit is <1 or >100 || search.Length>200) throw new ValidationFailedException("Некорректные параметры поиска.");
        return ApiResponse<IReadOnlyList<UploadInfo>>.Ok(await store.ListUploadsAsync(search,offset,limit,ct));
    }
    [HttpGet("{id:guid}")]
    public async Task<ActionResult<ApiResponse<UploadDetail>>> Get(Guid id,CancellationToken ct)
        => ApiResponse<UploadDetail>.Ok(await store.GetUploadAsync(id,ct) ?? throw new NotFoundException("Документ не найден."));
    [HttpPost("{id:guid}/parse")]
    public async Task<ActionResult<ApiResponse<UploadDetail>>> Parse(Guid id,[FromServices] ParseUploadHandler handler,CancellationToken ct)
        => ApiResponse<UploadDetail>.Ok(await handler.HandleAsync(id,ct));
    [HttpGet("{id:guid}/file")]
    public async Task<IActionResult> File(Guid id,CancellationToken ct)
    {
        var file=await store.GetUploadFileAsync(id,ct) ?? throw new NotFoundException("Исходный файл не найден.");
        return File(file.Content,file.ContentType,file.FileName);
    }
}
