using System.Text.Json;
using DomeoSpec.Application.Common;
using DomeoSpec.Application.Quotations;
using DomeoSpec.Domain.Quotations;
using Microsoft.Data.Sqlite;
namespace DomeoSpec.Infrastructure.Quotations;

public sealed partial class SqliteQuotationStore
{
    private const string ProjectColumns = "id,revision,updated_at,title,documents,positions,margin_percent,quotation_id";
    private static ProjectInfo ProjectInfoFrom(SqliteDataReader r) => new(Uuid(r, 0), r.GetInt64(1), Time(r.GetString(2)),
        r.GetString(3), r.GetInt32(4), r.GetInt32(5), DoubleN(r, 6), UuidN(r, 7));

    // Как в PostgreSQL-варианте: если наименование объекта пустое — показываем имя документа
    // (шифр, иначе имя файла первого тома) из снимка. В SQLite путь к полю — json_extract.
    private const string TitleExpr =
        "COALESCE(NULLIF(title,''), NULLIF(json_extract(snapshot,'$.documents[0].doc.doc_code'),''), json_extract(snapshot,'$.documents[0].doc.file_name'), '')";

    public Task<IReadOnlyList<ProjectInfo>> ListProjectsAsync(string search, int offset, int limit, CancellationToken ct) => Run<IReadOnlyList<ProjectInfo>>(async db =>
    {
        await using var cmd = db.CreateCommand();
        cmd.CommandText = $"SELECT id,revision,updated_at,{TitleExpr} AS title,documents,positions,margin_percent,quotation_id FROM spec_projects WHERE ($search='' OR instr(lower({TitleExpr}),lower($search))>0) ORDER BY updated_at DESC,id DESC LIMIT $limit OFFSET $offset";
        P(cmd, "$search", search); P(cmd, "$limit", limit); P(cmd, "$offset", offset);
        await using var r = (SqliteDataReader)await cmd.ExecuteReaderAsync(ct);
        var result = new List<ProjectInfo>();
        while (await r.ReadAsync(ct)) result.Add(ProjectInfoFrom(r));
        return result;
    }, ct);

    public Task<ProjectDetail?> GetProjectAsync(Guid id, CancellationToken ct) => Run(async db =>
    {
        await using var cmd = db.CreateCommand();
        cmd.CommandText = $"SELECT {ProjectColumns},snapshot FROM spec_projects WHERE id=$id";
        P(cmd, "$id", id.ToString());
        await using var r = (SqliteDataReader)await cmd.ExecuteReaderAsync(ct);
        return await r.ReadAsync(ct) ? new ProjectDetail(ProjectInfoFrom(r), JsonSerializer.Deserialize<QuotationSnapshot>(r.GetString(8), Json)!) : null;
    }, ct);

    public Task<ProjectInfo> SaveProjectAsync(Guid id, SaveProject request, string hash, CancellationToken ct) => Run(async db =>
    {
        // Доступ уже сериализован семафором (один писатель за раз); транзакция делает чтение-запись
        // атомарной при сбое. Проверка версии и идемпотентный повтор — как в PostgreSQL-варианте.
        await using var tx = (SqliteTransaction)await db.BeginTransactionAsync(ct);
        ProjectInfo? current = null;
        Guid? mutation = null;
        string? previousHash = null;
        await using (var select = db.CreateCommand())
        {
            select.Transaction = tx;
            select.CommandText = $"SELECT {ProjectColumns},mutation_id,request_hash FROM spec_projects WHERE id=$id";
            P(select, "$id", id.ToString());
            await using var r = (SqliteDataReader)await select.ExecuteReaderAsync(ct);
            if (await r.ReadAsync(ct)) { current = ProjectInfoFrom(r); mutation = Uuid(r, 8); previousHash = r.GetString(9); }
        }
        if (mutation == request.MutationId && hash == previousHash) return current!;
        if ((current?.Revision ?? 0) != request.ExpectedRevision || mutation == request.MutationId)
            throw new ConflictException("Объект уже изменён в другом окне. Откройте сохранённый объект или сохраните свои правки отдельной копией.");
        var s = request.Snapshot;
        var info = new ProjectInfo(id, (current?.Revision ?? 0) + 1, DateTime.UtcNow, s.Title,
            s.Documents.Count, s.Documents.Sum(d => d.Doc.Summary.Count(row => !row.Excluded)), s.Kp.MarginPercent, request.QuotationId);
        await using (var cmd = db.CreateCommand())
        {
            cmd.Transaction = tx;
            cmd.CommandText = """
                INSERT INTO spec_projects (id,revision,updated_at,title,documents,positions,margin_percent,quotation_id,mutation_id,request_hash,snapshot)
                VALUES ($id,$revision,$updated,$title,$documents,$positions,$margin,$quotation,$mutation,$hash,$snapshot)
                ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,updated_at=excluded.updated_at,title=excluded.title,
                  documents=excluded.documents,positions=excluded.positions,margin_percent=excluded.margin_percent,
                  quotation_id=excluded.quotation_id,mutation_id=excluded.mutation_id,request_hash=excluded.request_hash,snapshot=excluded.snapshot
                """;
            P(cmd, "$id", id.ToString()); P(cmd, "$revision", info.Revision); P(cmd, "$updated", Text(info.UpdatedAt));
            P(cmd, "$title", info.Title); P(cmd, "$documents", info.Documents); P(cmd, "$positions", info.Positions);
            P(cmd, "$margin", info.MarginPercent); P(cmd, "$quotation", info.QuotationId?.ToString());
            P(cmd, "$mutation", request.MutationId.ToString()); P(cmd, "$hash", hash);
            P(cmd, "$snapshot", JsonSerializer.Serialize(s, Json));
            await cmd.ExecuteNonQueryAsync(ct);
        }
        await tx.CommitAsync(ct);
        return info;
    }, ct);
}
