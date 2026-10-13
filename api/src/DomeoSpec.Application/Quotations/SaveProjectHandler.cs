using System.Security.Cryptography;
using System.Text.Json;
using DomeoSpec.Application.Common;
using DomeoSpec.Application.Uploads;
using DomeoSpec.Domain.Quotations;
namespace DomeoSpec.Application.Quotations;

public sealed class SaveProjectHandler(IProjectStore store, IUploadStore uploads, IQuotationStore quotations)
{
    public async Task<ProjectInfo> HandleAsync(Guid id, SaveProject request, CancellationToken ct)
    {
        var s = request.Snapshot;
        if (id == Guid.Empty || request.MutationId == Guid.Empty || request.ExpectedRevision < 0 ||
            s is null || s.Version != 1 || s.Documents is null || s.Kp is null || s.Indexation is null ||
            s.Title is null || s.Title.Length > 1000 || s.TemplateName is null || s.TemplateName.Length > 500 || s.Documents.Count > 100)
            throw new ValidationFailedException("Некорректные данные рабочего объекта.");
        if (s.Kp.MarginPercent is { } margin && (!double.IsFinite(margin) || margin < 0 || margin > 99.99))
            throw new ValidationFailedException("Маржа должна быть от 0 до 99,99%.");
        if (s.Documents.Any(d => d is null || d.Doc is null || d.Doc.Summary is null) ||
            s.Documents.Select(d => d.Id).Distinct().Count() != s.Documents.Count)
            throw new ValidationFailedException("Некорректные тома объекта.");
        // Оригиналы живут в архиве: автосохранение не копирует PDF при каждом изменении цены.
        foreach (var original in s.Documents.Select(d => d.Original).Where(o => o is not null))
        {
            if (original!.UploadId is not { } uploadId || await uploads.GetUploadAsync(uploadId, ct) is null)
                throw new ValidationFailedException("Сначала сохраните исходный файл в архив документов.");
            if (!string.IsNullOrEmpty(original.Content))
                throw new ValidationFailedException("Рабочий объект должен ссылаться на оригинал в архиве.");
        }
        if (request.QuotationId is { } quotationId)
        {
            var quotation = await quotations.GetAsync(quotationId, ct);
            if (quotation is null || quotation.Info.ProjectId != id)
                throw new ValidationFailedException("Версия КП относится к другому объекту.");
        }
        var hash = Convert.ToHexString(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(request)));
        return await store.SaveProjectAsync(id, request, hash, ct);
    }
}
