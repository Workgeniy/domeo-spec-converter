using DomeoSpec.Domain.Specifications;
namespace DomeoSpec.Domain.Quotations;

// Снимок содержит и исключённые строки: старое КП можно продолжить редактировать.
public sealed record QuotationSource(string Id, string Name, string Content, string? TemplateId = null, string? Warning = null, Guid? UploadId = null);
public sealed record QuotationDocument(string Id, string LoadedAt, ParsedDocument Doc, QuotationSource? Original = null);
public sealed record QuotationSnapshot
{
    public int Version { get; init; } = 1;
    public string Title { get; init; } = "";
    public IReadOnlyList<QuotationDocument> Documents { get; init; } = [];
    public KpSettings Kp { get; init; } = new();
    public Indexation Indexation { get; init; } = new();
    public string? Template { get; init; }
    public string TemplateName { get; init; } = "Стандартная форма";
}
public sealed record SaveQuotation(Guid Id, Guid ProjectId, Guid? ParentId, QuotationSnapshot Snapshot);
public sealed record QuotationInfo(Guid Id, Guid ProjectId, Guid? ParentId, DateTime CreatedAt,
    string Title, string ContractNumber, int Positions, double? MarginPercent, string TemplateName, string FileName);
public sealed record QuotationDetail(QuotationInfo Info, QuotationSnapshot Snapshot);
public sealed record StoredQuotation(QuotationInfo Info, QuotationSnapshot Snapshot, string RequestHash, byte[] Content, string ContentType);
