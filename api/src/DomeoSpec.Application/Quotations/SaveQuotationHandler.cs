using System.Security.Cryptography;
using System.Text.Json;
using DomeoSpec.Application.Common;
using DomeoSpec.Application.Parsing;
using DomeoSpec.Domain.Quotations;
using DomeoSpec.Domain.Specifications;
namespace DomeoSpec.Application.Quotations;

public sealed class SaveQuotationHandler(IQuotationStore store, ExportSpecificationHandler exporter, DomeoSpec.Application.Uploads.IUploadStore uploads)
{
    public async Task<QuotationInfo> HandleAsync(SaveQuotation request, CancellationToken ct)
    {
        var s = request.Snapshot;
        if (request.Id == Guid.Empty || request.ProjectId == Guid.Empty || s.Version != 1 || s.Documents.Count == 0)
            throw new ValidationFailedException("Для сохранения КП нужен объект с документами.");
        if (s.Title.Length > 1000 || s.Documents.Count > 100 || s.TemplateName.Length > 500)
            throw new ValidationFailedException("Слишком большое название объекта или количество томов.");
        var hash = Convert.ToHexString(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(request)));
        var previousHash = await store.GetRequestHashAsync(request.Id, ct);
        if (previousHash is not null) return await Existing(request.Id, hash, previousHash, ct);
        if (request.ParentId is { } parentId)
        {
            var parent = await store.GetAsync(parentId, ct) ?? throw new NotFoundException("Исходная версия КП не найдена.");
            if (parent.Info.ProjectId != request.ProjectId)
                throw new ValidationFailedException("Исходная версия относится к другому объекту.");
        }
        foreach (var d in s.Documents)
        {
            if (d.Original is not { } source) continue;
            if (source.UploadId is { } uploadId)
            {
                if (await uploads.GetUploadAsync(uploadId, ct) is null)
                    throw new ValidationFailedException("Исходный файл отсутствует в архиве документов.");
                continue;
            }
            if (source.Content.Length > 94_000_000 || source.Name.Length > 500)
                throw new ValidationFailedException("Исходный файл слишком большой для истории.");
            try { Convert.FromBase64String(source.Content); }
            catch (FormatException) { throw new ValidationFailedException("Повреждены данные исходного файла."); }
        }
        var rows = s.Documents.SelectMany(d => d.Doc.Summary).Where(r => !r.Excluded).ToArray();
        if (rows.Length == 0) throw new ValidationFailedException("Нет позиций для КП: все строки исключены или свод пуст.");
        var first = s.Documents[0].Doc;
        var title = string.IsNullOrWhiteSpace(s.Title) ? first.Title : s.Title;
        var document = first with
        {
            Title = title,
            FileName = s.Documents.Count == 1 ? first.FileName : "КП.xlsx",
            DocCode = string.Join(", ", s.Documents.Select(d => d.Doc.DocCode)),
            Summary = rows,
            Items = s.Documents.SelectMany(d => d.Doc.Items).ToArray(),
            Documents = s.Documents.SelectMany(d => d.Doc.Documents).ToArray(),
            Kp = s.Kp, KpTemplate = s.Template, Kind = "kp", Indexation = s.Indexation,
        };
        var file = await exporter.HandleAsync(document, ct);
        var info = new QuotationInfo(request.Id, request.ProjectId, request.ParentId, DateTime.UtcNow,
            title, s.Kp.ContractNumber, rows.Length, s.Kp.MarginPercent, s.TemplateName, file.FileName);
        // Один INSERT атомарно сохраняет снимок и готовые байты. Повтор запроса не создаёт дубль.
        await store.InsertAsync(new StoredQuotation(info, s, hash, file.Content, file.ContentType), ct);
        return await Existing(request.Id, hash, (await store.GetRequestHashAsync(request.Id, ct))!, ct);
    }
    private async Task<QuotationInfo> Existing(Guid id, string expected, string actual, CancellationToken ct)
    {
        if (expected != actual) throw new ValidationFailedException("Этот идентификатор КП уже использован для других данных.");
        return (await store.GetAsync(id, ct))!.Info;
    }
}
