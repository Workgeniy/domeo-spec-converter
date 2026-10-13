using System.Text.Json;
using DomeoSpec.Application.Parsing;
using DomeoSpec.Domain.Specifications;
using DomeoSpec.Domain.Uploads;
using Npgsql;
using NpgsqlTypes;
namespace DomeoSpec.Infrastructure.Quotations;
public sealed partial class PostgresQuotationStore
{
    private const string UploadColumns = "id, project_id, created_at, file_name, title, size, sha256, document IS NOT NULL, error";
    private static UploadInfo ReadUpload(NpgsqlDataReader r) => new(r.GetGuid(0), r.GetGuid(1), r.GetDateTime(2),
        r.GetString(3), r.GetString(4), r.GetInt64(5), r.GetString(6), r.GetBoolean(7), r.IsDBNull(8) ? null : r.GetString(8));
    public Task<UploadInfo> SaveUploadAsync(UploadInfo i, byte[] content, string type, CancellationToken ct) => Run(async db =>
    {
        await using var cmd = db.CreateCommand("""
            INSERT INTO spec_uploads (id,project_id,created_at,file_name,title,size,sha256,content_type,content)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT(project_id,file_name,sha256) DO NOTHING
            """);
        cmd.Parameters.AddWithValue(i.Id); cmd.Parameters.AddWithValue(i.ProjectId); cmd.Parameters.AddWithValue(i.CreatedAt);
        cmd.Parameters.AddWithValue(i.FileName); cmd.Parameters.AddWithValue(i.Title); cmd.Parameters.AddWithValue(i.Size);
        cmd.Parameters.AddWithValue(i.Sha256); cmd.Parameters.AddWithValue(type); cmd.Parameters.AddWithValue(content);
        await cmd.ExecuteNonQueryAsync(ct);
        // Отдельный SELECT видит запись параллельного загрузчика после ожидания UNIQUE.
        await using var find = db.CreateCommand($"SELECT {UploadColumns} FROM spec_uploads WHERE project_id=$1 AND file_name=$2 AND sha256=$3");
        find.Parameters.AddWithValue(i.ProjectId); find.Parameters.AddWithValue(i.FileName); find.Parameters.AddWithValue(i.Sha256);
        await using var reader = await find.ExecuteReaderAsync(ct);
        await reader.ReadAsync(ct);
        return ReadUpload(reader);
    }, ct);
    public Task<IReadOnlyList<UploadInfo>> ListUploadsAsync(string search, int offset, int limit, CancellationToken ct) => Run<IReadOnlyList<UploadInfo>>(async db =>
    {
        await using var cmd = db.CreateCommand($"SELECT {UploadColumns} FROM spec_uploads WHERE $1='' OR strpos(lower(title || ' ' || file_name),lower($1))>0 ORDER BY created_at DESC,id DESC LIMIT $2 OFFSET $3");
        cmd.Parameters.AddWithValue(search); cmd.Parameters.AddWithValue(limit); cmd.Parameters.AddWithValue(offset);
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        var rows = new List<UploadInfo>();
        while (await reader.ReadAsync(ct)) rows.Add(ReadUpload(reader));
        return rows;
    }, ct);
    public Task<UploadDetail?> GetUploadAsync(Guid id, CancellationToken ct) => Run(async db =>
    {
        await using var cmd = db.CreateCommand($"SELECT {UploadColumns},document::text FROM spec_uploads WHERE id=$1");
        cmd.Parameters.AddWithValue(id);
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        return await reader.ReadAsync(ct) ? new UploadDetail(ReadUpload(reader), reader.IsDBNull(9) ? null :
            JsonSerializer.Deserialize<ParsedDocument>(reader.GetString(9), Json)) : null;
    }, ct);
    public Task<ExportedFile?> GetUploadFileAsync(Guid id, CancellationToken ct) => Run(async db =>
    {
        await using var cmd = db.CreateCommand("SELECT content,file_name,content_type FROM spec_uploads WHERE id=$1");
        cmd.Parameters.AddWithValue(id);
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        return await reader.ReadAsync(ct) ? new ExportedFile(reader.GetFieldValue<byte[]>(0),reader.GetString(1),reader.GetString(2)) : null;
    }, ct);
    public Task SetUploadResultAsync(Guid id, ParsedDocument? document, string? error, CancellationToken ct) => Run(async db =>
    {
        // Успешный результат не затирается ошибкой другого одновременного запроса.
        await using var cmd = db.CreateCommand("""
            UPDATE spec_uploads SET document=$2, error=$3,
                title=CASE WHEN title='' THEN $4 ELSE title END
            WHERE id=$1 AND document IS NULL
            """);
        cmd.Parameters.AddWithValue(id);
        cmd.Parameters.Add(new NpgsqlParameter { NpgsqlDbType=NpgsqlDbType.Jsonb, Value=document is null ? DBNull.Value : JsonSerializer.Serialize(document,Json) });
        cmd.Parameters.Add(new NpgsqlParameter { NpgsqlDbType=NpgsqlDbType.Text, Value=(object?)error ?? DBNull.Value });
        cmd.Parameters.AddWithValue(document?.Title ?? "");
        return await cmd.ExecuteNonQueryAsync(ct);
    }, ct);
}
