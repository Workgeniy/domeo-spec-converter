using System.Text.Json;
using DomeoSpec.Application.Parsing;
using DomeoSpec.Domain.Specifications;
using DomeoSpec.Domain.Uploads;
using Microsoft.Data.Sqlite;
namespace DomeoSpec.Infrastructure.Quotations;

public sealed partial class SqliteQuotationStore
{
    private const string UploadColumns = "id, project_id, created_at, file_name, title, size, sha256, document IS NOT NULL, error";
    private static UploadInfo ReadUpload(SqliteDataReader r) => new(Uuid(r, 0), Uuid(r, 1), Time(r.GetString(2)),
        r.GetString(3), r.GetString(4), r.GetInt64(5), r.GetString(6), r.GetBoolean(7), r.IsDBNull(8) ? null : r.GetString(8));

    public Task<UploadInfo> SaveUploadAsync(UploadInfo i, byte[] content, string type, CancellationToken ct) => Run(async db =>
    {
        await using (var cmd = db.CreateCommand())
        {
            cmd.CommandText = """
                INSERT INTO spec_uploads (id,project_id,created_at,file_name,title,size,sha256,content_type,content)
                VALUES ($id,$project,$created,$file,$title,$size,$sha,$type,$content) ON CONFLICT(project_id,file_name,sha256) DO NOTHING
                """;
            P(cmd, "$id", i.Id.ToString()); P(cmd, "$project", i.ProjectId.ToString()); P(cmd, "$created", Text(i.CreatedAt));
            P(cmd, "$file", i.FileName); P(cmd, "$title", i.Title); P(cmd, "$size", i.Size);
            P(cmd, "$sha", i.Sha256); P(cmd, "$type", type); P(cmd, "$content", content);
            await cmd.ExecuteNonQueryAsync(ct);
        }
        // Повторный SELECT возвращает актуальную запись (в т.ч. при конфликте по UNIQUE — ту, что уже есть).
        await using var find = db.CreateCommand();
        find.CommandText = $"SELECT {UploadColumns} FROM spec_uploads WHERE project_id=$project AND file_name=$file AND sha256=$sha";
        P(find, "$project", i.ProjectId.ToString()); P(find, "$file", i.FileName); P(find, "$sha", i.Sha256);
        await using var reader = (SqliteDataReader)await find.ExecuteReaderAsync(ct);
        await reader.ReadAsync(ct);
        return ReadUpload(reader);
    }, ct);

    public Task<IReadOnlyList<UploadInfo>> ListUploadsAsync(string search, int offset, int limit, CancellationToken ct) => Run<IReadOnlyList<UploadInfo>>(async db =>
    {
        await using var cmd = db.CreateCommand();
        cmd.CommandText = $"SELECT {UploadColumns} FROM spec_uploads WHERE $search='' OR instr(lower(title || ' ' || file_name),lower($search))>0 ORDER BY created_at DESC,id DESC LIMIT $limit OFFSET $offset";
        P(cmd, "$search", search); P(cmd, "$limit", limit); P(cmd, "$offset", offset);
        await using var reader = (SqliteDataReader)await cmd.ExecuteReaderAsync(ct);
        var rows = new List<UploadInfo>();
        while (await reader.ReadAsync(ct)) rows.Add(ReadUpload(reader));
        return rows;
    }, ct);

    public Task<UploadDetail?> GetUploadAsync(Guid id, CancellationToken ct) => Run(async db =>
    {
        await using var cmd = db.CreateCommand();
        cmd.CommandText = $"SELECT {UploadColumns},document FROM spec_uploads WHERE id=$id";
        P(cmd, "$id", id.ToString());
        await using var reader = (SqliteDataReader)await cmd.ExecuteReaderAsync(ct);
        return await reader.ReadAsync(ct) ? new UploadDetail(ReadUpload(reader), reader.IsDBNull(9) ? null :
            JsonSerializer.Deserialize<ParsedDocument>(reader.GetString(9), Json)) : null;
    }, ct);

    public Task<ExportedFile?> GetUploadFileAsync(Guid id, CancellationToken ct) => Run(async db =>
    {
        await using var cmd = db.CreateCommand();
        cmd.CommandText = "SELECT content,file_name,content_type FROM spec_uploads WHERE id=$id";
        P(cmd, "$id", id.ToString());
        await using var reader = (SqliteDataReader)await cmd.ExecuteReaderAsync(ct);
        return await reader.ReadAsync(ct) ? new ExportedFile(reader.GetFieldValue<byte[]>(0), reader.GetString(1), reader.GetString(2)) : null;
    }, ct);

    public Task SetUploadResultAsync(Guid id, ParsedDocument? document, string? error, CancellationToken ct) => Run(async db =>
    {
        // Успешный результат не затирается ошибкой другого одновременного запроса (document IS NULL).
        await using var cmd = db.CreateCommand();
        cmd.CommandText = """
            UPDATE spec_uploads SET document=$document, error=$error,
                title=CASE WHEN title='' THEN $title ELSE title END
            WHERE id=$id AND document IS NULL
            """;
        P(cmd, "$id", id.ToString());
        P(cmd, "$document", document is null ? null : JsonSerializer.Serialize(document, Json));
        P(cmd, "$error", error);
        P(cmd, "$title", document?.Title ?? "");
        return await cmd.ExecuteNonQueryAsync(ct);
    }, ct);
}
