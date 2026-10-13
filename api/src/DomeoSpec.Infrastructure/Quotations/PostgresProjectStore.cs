using System.Text.Json;
using DomeoSpec.Application.Common;
using DomeoSpec.Application.Quotations;
using DomeoSpec.Domain.Quotations;
using Npgsql;
using NpgsqlTypes;
namespace DomeoSpec.Infrastructure.Quotations;

public sealed partial class PostgresQuotationStore : IProjectStore
{
    private const string ProjectColumns = "id,revision,updated_at,title,documents,positions,margin_percent,quotation_id";
    private static ProjectInfo ProjectInfoFrom(NpgsqlDataReader r) => new(r.GetGuid(0), r.GetInt64(1), r.GetDateTime(2),
        r.GetString(3), r.GetInt32(4), r.GetInt32(5), r.IsDBNull(6) ? null : r.GetDouble(6), r.IsDBNull(7) ? null : r.GetGuid(7));

    public Task<IReadOnlyList<ProjectInfo>> ListProjectsAsync(string search, int offset, int limit, CancellationToken ct) => Run<IReadOnlyList<ProjectInfo>>(async db =>
    {
        await using var cmd = db.CreateCommand($"SELECT {ProjectColumns} FROM spec_projects WHERE ($1='' OR strpos(lower(title),lower($1))>0) ORDER BY updated_at DESC,id DESC LIMIT $2 OFFSET $3");
        cmd.Parameters.AddWithValue(search); cmd.Parameters.AddWithValue(limit); cmd.Parameters.AddWithValue(offset);
        await using var r = await cmd.ExecuteReaderAsync(ct);
        var result = new List<ProjectInfo>();
        while (await r.ReadAsync(ct)) result.Add(ProjectInfoFrom(r));
        return result;
    }, ct);

    public Task<ProjectDetail?> GetProjectAsync(Guid id, CancellationToken ct) => Run(async db =>
    {
        await using var cmd = db.CreateCommand($"SELECT {ProjectColumns},snapshot::text FROM spec_projects WHERE id=$1");
        cmd.Parameters.AddWithValue(id);
        await using var r = await cmd.ExecuteReaderAsync(ct);
        return await r.ReadAsync(ct) ? new ProjectDetail(ProjectInfoFrom(r), JsonSerializer.Deserialize<QuotationSnapshot>(r.GetString(8), Json)!) : null;
    }, ct);

    public Task<ProjectInfo> SaveProjectAsync(Guid id, SaveProject request, string hash, CancellationToken ct) => Run(async db =>
    {
        await using var connection = await db.OpenConnectionAsync(ct);
        await using var tx = await connection.BeginTransactionAsync(ct);
        // Блокировка по объекту защищает также первую вставку и повтор потерянного ответа.
        await using (var guard = new NpgsqlCommand("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", connection, tx))
        {
            guard.Parameters.AddWithValue(id.ToString()); await guard.ExecuteNonQueryAsync(ct);
        }
        ProjectInfo? current = null;
        Guid? mutation = null;
        string? previousHash = null;
        await using (var select = new NpgsqlCommand($"SELECT {ProjectColumns},mutation_id,request_hash FROM spec_projects WHERE id=$1", connection, tx))
        {
            select.Parameters.AddWithValue(id);
            await using var r = await select.ExecuteReaderAsync(ct);
            if (await r.ReadAsync(ct)) { current = ProjectInfoFrom(r); mutation = r.GetGuid(8); previousHash = r.GetString(9); }
        }
        if (mutation == request.MutationId && hash == previousHash) return current!;
        if ((current?.Revision ?? 0) != request.ExpectedRevision || mutation == request.MutationId)
            throw new ConflictException("Объект уже изменён в другом окне. Откройте сохранённый объект или сохраните свои правки отдельной копией.");
        var s = request.Snapshot;
        var info = new ProjectInfo(id, (current?.Revision ?? 0) + 1, DateTime.UtcNow, s.Title,
            s.Documents.Count, s.Documents.Sum(d => d.Doc.Summary.Count(r => !r.Excluded)), s.Kp.MarginPercent, request.QuotationId);
        await using var cmd = new NpgsqlCommand("""
            INSERT INTO spec_projects (id,revision,updated_at,title,documents,positions,margin_percent,quotation_id,mutation_id,request_hash,snapshot)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            ON CONFLICT(id) DO UPDATE SET revision=EXCLUDED.revision,updated_at=EXCLUDED.updated_at,title=EXCLUDED.title,
              documents=EXCLUDED.documents,positions=EXCLUDED.positions,margin_percent=EXCLUDED.margin_percent,
              quotation_id=EXCLUDED.quotation_id,mutation_id=EXCLUDED.mutation_id,request_hash=EXCLUDED.request_hash,snapshot=EXCLUDED.snapshot
            """, connection, tx);
        cmd.Parameters.AddWithValue(id); cmd.Parameters.AddWithValue(info.Revision); cmd.Parameters.AddWithValue(info.UpdatedAt);
        cmd.Parameters.AddWithValue(info.Title); cmd.Parameters.AddWithValue(info.Documents); cmd.Parameters.AddWithValue(info.Positions);
        cmd.Parameters.Add(new NpgsqlParameter { NpgsqlDbType = NpgsqlDbType.Double, Value = (object?)info.MarginPercent ?? DBNull.Value });
        cmd.Parameters.Add(new NpgsqlParameter { NpgsqlDbType = NpgsqlDbType.Uuid, Value = (object?)info.QuotationId ?? DBNull.Value });
        cmd.Parameters.AddWithValue(request.MutationId); cmd.Parameters.AddWithValue(hash);
        cmd.Parameters.AddWithValue(NpgsqlDbType.Jsonb, JsonSerializer.Serialize(s, Json));
        await cmd.ExecuteNonQueryAsync(ct);
        await tx.CommitAsync(ct);
        return info;
    }, ct);
}
