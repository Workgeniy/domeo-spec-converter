using DomeoSpec.Domain.Specifications;
namespace DomeoSpec.Domain.Uploads;
public sealed record UploadInfo(Guid Id, Guid ProjectId, DateTime CreatedAt, string FileName, string Title,
    long Size, string Sha256, bool Parsed, string? Error);
public sealed record UploadDetail(UploadInfo Info, ParsedDocument? Document);
