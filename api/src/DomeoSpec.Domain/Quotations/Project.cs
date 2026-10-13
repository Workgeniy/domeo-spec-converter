namespace DomeoSpec.Domain.Quotations;

// Рабочий объект изменяется; сформированные КП остаются отдельными неизменяемыми версиями.
public sealed record SaveProject(long ExpectedRevision, Guid MutationId, QuotationSnapshot Snapshot, Guid? QuotationId = null);
public sealed record ProjectInfo(Guid Id, long Revision, DateTime UpdatedAt, string Title,
    int Documents, int Positions, double? MarginPercent, Guid? QuotationId);
public sealed record ProjectDetail(ProjectInfo Info, QuotationSnapshot Snapshot);
