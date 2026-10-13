using DomeoSpec.Domain.Quotations;
using DomeoSpec.Domain.Specifications;
using DomeoSpec.Application.Parsing;
namespace DomeoSpec.Application.Quotations;
public interface IQuotationStore
{
    Task<IReadOnlyList<QuotationInfo>> ListAsync(string search, Guid? projectId, int offset, int limit, CancellationToken ct);
    Task<QuotationDetail?> GetAsync(Guid id, CancellationToken ct);
    Task<string?> GetRequestHashAsync(Guid id, CancellationToken ct);
    Task<ExportedFile?> GetFileAsync(Guid id, CancellationToken ct);
    Task InsertAsync(StoredQuotation quotation, CancellationToken ct);
}
