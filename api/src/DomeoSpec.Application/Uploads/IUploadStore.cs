using DomeoSpec.Application.Parsing;
using DomeoSpec.Domain.Specifications;
using DomeoSpec.Domain.Uploads;
namespace DomeoSpec.Application.Uploads;
public interface IUploadStore
{
    Task<UploadInfo> SaveUploadAsync(UploadInfo info, byte[] content, string contentType, CancellationToken ct);
    Task<IReadOnlyList<UploadInfo>> ListUploadsAsync(string search, int offset, int limit, CancellationToken ct);
    Task<UploadDetail?> GetUploadAsync(Guid id, CancellationToken ct);
    Task<ExportedFile?> GetUploadFileAsync(Guid id, CancellationToken ct);
    Task SetUploadResultAsync(Guid id, ParsedDocument? document, string? error, CancellationToken ct);
}
