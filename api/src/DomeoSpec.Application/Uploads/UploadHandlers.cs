using System.Security.Cryptography;
using DomeoSpec.Application.Common;
using DomeoSpec.Application.Parsing;
using DomeoSpec.Domain.Uploads;
namespace DomeoSpec.Application.Uploads;

public sealed class SaveUploadHandler(IUploadStore store)
{
    public async Task<UploadInfo> HandleAsync(Stream stream, string fileName, long length, Guid projectId, string title, CancellationToken ct)
    {
        ParseSpecificationHandler.Validate(fileName, length);
        if (projectId == Guid.Empty || title.Length > 1000 || fileName.Length > 500)
            throw new ValidationFailedException("Некорректный объект или слишком длинное имя файла.");
        var content = new byte[checked((int)length)];
        try { await stream.ReadExactlyAsync(content, ct); }
        catch (EndOfStreamException) { throw new ValidationFailedException("Файл загружен не полностью."); }
        var hash = Convert.ToHexString(SHA256.HashData(content));
        var type = Path.GetExtension(fileName).ToLowerInvariant() switch
        {
            ".pdf" => "application/pdf",
            ".xlsm" => "application/vnd.ms-excel.sheet.macroEnabled.12",
            _ => "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        };
        return await store.SaveUploadAsync(new UploadInfo(Guid.NewGuid(), projectId, DateTime.UtcNow,
            fileName, title, length, hash, false, null), content, type, ct);
    }
}
public sealed class ParseUploadHandler(IUploadStore store, ParseSpecificationHandler parser)
{
    public async Task<UploadDetail> HandleAsync(Guid id, CancellationToken ct)
    {
        var saved = await store.GetUploadAsync(id, ct) ?? throw new NotFoundException("Документ не найден.");
        if (saved.Document is not null) return saved;
        var file = await store.GetUploadFileAsync(id, ct) ?? throw new NotFoundException("Исходный файл не найден.");
        try
        {
            using var stream = new MemoryStream(file.Content, writable: false);
            var document = await parser.HandleAsync(stream, file.FileName, file.Content.Length, ct);
            await store.SetUploadResultAsync(id, document, null, ct);
            return (await store.GetUploadAsync(id, ct))!;
        }
        catch (Exception ex) when (ex is EngineFailureException or ServiceUnavailableException or ValidationFailedException)
        {
            await store.SetUploadResultAsync(id, null, ex.Message[..Math.Min(ex.Message.Length, 1000)], ct);
            throw;
        }
    }
}
