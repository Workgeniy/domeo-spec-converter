using System.Text.Json;
using DomeoSpec.Application.Common;
using DomeoSpec.Application.Quotations;
using DomeoSpec.Domain.Quotations;
using DomeoSpec.Domain.Specifications;
using DomeoSpec.Application.Parsing;
using Microsoft.Extensions.Configuration;
using Npgsql;
using NpgsqlTypes;
namespace DomeoSpec.Infrastructure.Quotations;

public sealed partial class PostgresQuotationStore : IQuotationStore, DomeoSpec.Application.Uploads.IUploadStore, IDisposable
{
    private readonly NpgsqlDataSource? source;
    private readonly SemaphoreSlim initialization = new(1, 1);
    private bool ready;
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    public PostgresQuotationStore(IConfiguration configuration)
    {
        var connection = configuration.GetConnectionString("Quotations");
        if (!string.IsNullOrWhiteSpace(connection))
            source = NpgsqlDataSource.Create(new NpgsqlConnectionStringBuilder(connection)
                { MaxPoolSize = 5, MinPoolSize = 0, Timeout = 5, CommandTimeout = 30 }.ConnectionString);
    }
    private async Task<T> Run<T>(Func<NpgsqlDataSource, Task<T>> action, CancellationToken ct)
    {
        if (source is null) throw new ServiceUnavailableException("База документов и истории КП не настроена. Укажите ConnectionStrings:Quotations.");
        try
        {
            await EnsureSchema(ct);
            return await action(source);
        }
        catch (NpgsqlException ex) { throw new ServiceUnavailableException("База документов и истории КП недоступна. Повторите сохранение позже; правки остаются в браузере.", ex); }
    }
    private async Task EnsureSchema(CancellationToken ct)
    {
        if (ready) return;
        await initialization.WaitAsync(ct);
        try
        {
            if (ready) return;
            await using var connection = await source!.OpenConnectionAsync(ct);
            await using var tx = await connection.BeginTransactionAsync(ct);
            // Сериализуем миграцию между процессами API.
            await using var command = new NpgsqlCommand("""
                SELECT pg_advisory_xact_lock(824319650);
                CREATE TABLE IF NOT EXISTS spec_projects (
                    id uuid PRIMARY KEY, revision bigint NOT NULL, updated_at timestamptz NOT NULL,
                    title text NOT NULL, documents integer NOT NULL, positions integer NOT NULL,
                    margin_percent double precision NULL, quotation_id uuid NULL,
                    mutation_id uuid NOT NULL, request_hash text NOT NULL, snapshot jsonb NOT NULL
                );
                CREATE INDEX IF NOT EXISTS spec_projects_updated ON spec_projects(updated_at DESC,id DESC);
                CREATE TABLE IF NOT EXISTS spec_uploads (
                    id uuid PRIMARY KEY, project_id uuid NOT NULL, created_at timestamptz NOT NULL,
                    file_name text NOT NULL, title text NOT NULL, size bigint NOT NULL,
                    sha256 text NOT NULL, content_type text NOT NULL, content bytea NOT NULL,
                    document jsonb NULL, error text NULL,
                    UNIQUE(project_id, file_name, sha256)
                );
                CREATE INDEX IF NOT EXISTS spec_uploads_created ON spec_uploads(created_at DESC, id DESC);
                CREATE TABLE IF NOT EXISTS spec_quotations (
                    id uuid PRIMARY KEY, project_id uuid NOT NULL, parent_id uuid NULL REFERENCES spec_quotations(id),
                    created_at timestamptz NOT NULL, title text NOT NULL, contract_number text NOT NULL,
                    positions integer NOT NULL, margin_percent double precision NULL, template_name text NOT NULL,
                    file_name text NOT NULL, content_type text NOT NULL, request_hash text NOT NULL,
                    snapshot jsonb NOT NULL, content bytea NOT NULL
                );
                CREATE INDEX IF NOT EXISTS spec_quotations_project ON spec_quotations(project_id, created_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS spec_quotations_created ON spec_quotations(created_at DESC, id DESC);
                """, connection, tx);
            await command.ExecuteNonQueryAsync(ct);
            await tx.CommitAsync(ct);
            ready = true;
        }
        finally { initialization.Release(); }
    }
    private const string Columns = "id,project_id,parent_id,created_at,title,contract_number,positions,margin_percent,template_name,file_name";
    private static QuotationInfo Info(NpgsqlDataReader r) => new(r.GetGuid(0), r.GetGuid(1), r.IsDBNull(2) ? null : r.GetGuid(2),
        r.GetDateTime(3), r.GetString(4), r.GetString(5), r.GetInt32(6), r.IsDBNull(7) ? null : r.GetDouble(7), r.GetString(8), r.GetString(9));
    public Task<IReadOnlyList<QuotationInfo>> ListAsync(string search, Guid? projectId, int offset, int limit, CancellationToken ct) => Run<IReadOnlyList<QuotationInfo>>(async db =>
    {
        await using var cmd = db.CreateCommand($"SELECT {Columns} FROM spec_quotations WHERE ($1 = '' OR strpos(lower(title || ' ' || contract_number),lower($1)) > 0) AND ($2::uuid IS NULL OR project_id=$2) ORDER BY created_at DESC,id DESC LIMIT $3 OFFSET $4");
        cmd.Parameters.AddWithValue(search);
        cmd.Parameters.Add(new NpgsqlParameter { NpgsqlDbType = NpgsqlDbType.Uuid, Value = (object?)projectId ?? DBNull.Value });
        cmd.Parameters.AddWithValue(limit); cmd.Parameters.AddWithValue(offset);
        await using var r = await cmd.ExecuteReaderAsync(ct);
        var result = new List<QuotationInfo>();
        while (await r.ReadAsync(ct)) result.Add(Info(r));
        return result;
    }, ct);
    public Task<QuotationDetail?> GetAsync(Guid id, CancellationToken ct) => Run(async db =>
    {
        await using var cmd = db.CreateCommand($"SELECT {Columns},snapshot::text FROM spec_quotations WHERE id=$1");
        cmd.Parameters.AddWithValue(id);
        await using var r = await cmd.ExecuteReaderAsync(ct);
        return await r.ReadAsync(ct) ? new QuotationDetail(Info(r), JsonSerializer.Deserialize<QuotationSnapshot>(r.GetString(10), Json)!) : null;
    }, ct);
    public Task<string?> GetRequestHashAsync(Guid id, CancellationToken ct) => Run(async db =>
    {
        await using var cmd = db.CreateCommand("SELECT request_hash FROM spec_quotations WHERE id=$1");
        cmd.Parameters.AddWithValue(id);
        return await cmd.ExecuteScalarAsync(ct) as string;
    }, ct);
    public Task<ExportedFile?> GetFileAsync(Guid id, CancellationToken ct) => Run(async db =>
    {
        await using var cmd = db.CreateCommand("SELECT content,file_name,content_type FROM spec_quotations WHERE id=$1");
        cmd.Parameters.AddWithValue(id);
        await using var r = await cmd.ExecuteReaderAsync(ct);
        return await r.ReadAsync(ct) ? new ExportedFile(r.GetFieldValue<byte[]>(0),r.GetString(1),r.GetString(2)) : null;
    }, ct);
    public Task InsertAsync(StoredQuotation q, CancellationToken ct) => Run(async db =>
    {
        await using var cmd = db.CreateCommand("""
            INSERT INTO spec_quotations (id,project_id,parent_id,created_at,title,contract_number,positions,margin_percent,template_name,file_name,content_type,request_hash,snapshot,content)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) ON CONFLICT(id) DO NOTHING
            """);
        var i=q.Info;
        cmd.Parameters.AddWithValue(i.Id); cmd.Parameters.AddWithValue(i.ProjectId);
        cmd.Parameters.Add(new NpgsqlParameter { NpgsqlDbType=NpgsqlDbType.Uuid,Value=(object?)i.ParentId ?? DBNull.Value });
        cmd.Parameters.AddWithValue(i.CreatedAt); cmd.Parameters.AddWithValue(i.Title); cmd.Parameters.AddWithValue(i.ContractNumber);
        cmd.Parameters.AddWithValue(i.Positions);
        cmd.Parameters.Add(new NpgsqlParameter { NpgsqlDbType=NpgsqlDbType.Double,Value=(object?)i.MarginPercent ?? DBNull.Value });
        cmd.Parameters.AddWithValue(i.TemplateName); cmd.Parameters.AddWithValue(i.FileName); cmd.Parameters.AddWithValue(q.ContentType);
        cmd.Parameters.AddWithValue(q.RequestHash); cmd.Parameters.AddWithValue(NpgsqlDbType.Jsonb,JsonSerializer.Serialize(q.Snapshot,Json));
        cmd.Parameters.AddWithValue(q.Content);
        return await cmd.ExecuteNonQueryAsync(ct);
    }, ct);
    public void Dispose() { source?.Dispose(); initialization.Dispose(); }
}
