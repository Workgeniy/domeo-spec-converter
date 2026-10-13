using DomeoSpec.Domain.Quotations;
namespace DomeoSpec.Application.Quotations;

public interface IProjectStore
{
    Task<IReadOnlyList<ProjectInfo>> ListProjectsAsync(string search, int offset, int limit, CancellationToken ct);
    Task<ProjectDetail?> GetProjectAsync(Guid id, CancellationToken ct);
    // Проверка версии и запись выполняются атомарно; повтор mutation_id идемпотентен.
    Task<ProjectInfo> SaveProjectAsync(Guid id, SaveProject request, string hash, CancellationToken ct);
}
