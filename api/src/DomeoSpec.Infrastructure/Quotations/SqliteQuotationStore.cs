using System.Globalization;
using System.Text.Json;
using DomeoSpec.Application.Common;
using DomeoSpec.Application.Parsing;
using DomeoSpec.Application.Quotations;
using DomeoSpec.Domain.Quotations;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.Configuration;
namespace DomeoSpec.Infrastructure.Quotations;

/// <summary>Встроенное файловое хранилище истории КП, объектов и загрузок на SQLite — для
/// автономного десктопа: движок компилируется в процесс (Microsoft.Data.Sqlite), отдельного
/// процесса/службы PostgreSQL не нужно. Один пользователь, один процесс API — поэтому держим одно
/// соединение и сериализуем доступ семафором; этого достаточно для корректности и снимает весь
/// класс блокировок SQLite. Серверный/сетевой режим по-прежнему на PostgreSQL (см.
/// <see cref="PostgresQuotationStore"/>); реализацию выбирает DI по строке подключения.</summary>
public sealed partial class SqliteQuotationStore : IQuotationStore, IProjectStore, DomeoSpec.Application.Uploads.IUploadStore, IDisposable
{
    private readonly string? dataSource;
    private readonly SemaphoreSlim gate = new(1, 1);
    private SqliteConnection? connection;
    private bool ready;
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };

    public SqliteQuotationStore(IConfiguration configuration)
        => dataSource = configuration.GetConnectionString("Quotations");

    // Всё обращение к БД — под семафором: одно соединение, один писатель за раз. Схема создаётся
    // один раз лениво. SqliteException → 503 с внятным текстом (как у PostgreSQL-варианта);
    // ConflictException пробрасывается наружу.
    private async Task<T> Run<T>(Func<SqliteConnection, Task<T>> action, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(dataSource))
            throw new ServiceUnavailableException("База документов и истории КП не настроена. Укажите ConnectionStrings:Quotations.");
        await gate.WaitAsync(ct);
        try
        {
            var db = await EnsureOpen(ct);
            return await action(db);
        }
        catch (SqliteException ex) { throw new ServiceUnavailableException("База документов и истории КП недоступна. Повторите сохранение позже; правки остаются в браузере.", ex); }
        finally { gate.Release(); }
    }

    private async Task<SqliteConnection> EnsureOpen(CancellationToken ct)
    {
        if (connection is not null && ready) return connection;
        // Держим одно соединение на весь срок службы, пул не нужен; без пула Dispose реально
        // закрывает файл (можно безопасно удалять/заменять .db).
        var builder = new SqliteConnectionStringBuilder(dataSource) { Mode = SqliteOpenMode.ReadWriteCreate, Pooling = false };
        var path = builder.DataSource;
        if (!string.IsNullOrEmpty(path) && Path.GetDirectoryName(Path.GetFullPath(path)) is { Length: > 0 } dir)
            Directory.CreateDirectory(dir);
        connection = new SqliteConnection(builder.ConnectionString);
        await connection.OpenAsync(ct);
        // Встроенный lower() в SQLite переводит в нижний регистр только ASCII — для поиска по
        // кириллице подменяем его управляемой реализацией .NET (знает Unicode).
        connection.CreateFunction<string?, string?>("lower", s => s?.ToLowerInvariant());
        await using (var pragma = connection.CreateCommand())
        {
            pragma.CommandText = "PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON;";
            await pragma.ExecuteNonQueryAsync(ct);
        }
        await EnsureSchema(connection, ct);
        ready = true;
        return connection;
    }

    private static async Task EnsureSchema(SqliteConnection db, CancellationToken ct)
    {
        await using var command = db.CreateCommand();
        // Схема повторяет PostgreSQL-вариант (EnsureSchema в PostgresQuotationStore) в типах SQLite:
        // uuid→TEXT, timestamptz→TEXT (ISO-8601), jsonb→TEXT, bytea→BLOB. Менять синхронно.
        command.CommandText = """
            CREATE TABLE IF NOT EXISTS spec_projects (
                id TEXT PRIMARY KEY, revision INTEGER NOT NULL, updated_at TEXT NOT NULL,
                title TEXT NOT NULL, documents INTEGER NOT NULL, positions INTEGER NOT NULL,
                margin_percent REAL NULL, quotation_id TEXT NULL,
                mutation_id TEXT NOT NULL, request_hash TEXT NOT NULL, snapshot TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS spec_projects_updated ON spec_projects(updated_at DESC, id DESC);
            CREATE TABLE IF NOT EXISTS spec_uploads (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, created_at TEXT NOT NULL,
                file_name TEXT NOT NULL, title TEXT NOT NULL, size INTEGER NOT NULL,
                sha256 TEXT NOT NULL, content_type TEXT NOT NULL, content BLOB NOT NULL,
                document TEXT NULL, error TEXT NULL,
                UNIQUE(project_id, file_name, sha256)
            );
            CREATE INDEX IF NOT EXISTS spec_uploads_created ON spec_uploads(created_at DESC, id DESC);
            CREATE TABLE IF NOT EXISTS spec_quotations (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, parent_id TEXT NULL REFERENCES spec_quotations(id),
                created_at TEXT NOT NULL, title TEXT NOT NULL, contract_number TEXT NOT NULL,
                positions INTEGER NOT NULL, margin_percent REAL NULL, template_name TEXT NOT NULL,
                file_name TEXT NOT NULL, content_type TEXT NOT NULL, request_hash TEXT NOT NULL,
                snapshot TEXT NOT NULL, content BLOB NOT NULL
            );
            CREATE INDEX IF NOT EXISTS spec_quotations_project ON spec_quotations(project_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS spec_quotations_created ON spec_quotations(created_at DESC, id DESC);
            """;
        await command.ExecuteNonQueryAsync(ct);
    }

    // --- хелперы хранения значений в колонках SQLite ---
    private static void P(SqliteCommand c, string name, object? value) => c.Parameters.AddWithValue(name, value ?? DBNull.Value);
    private static string Text(DateTime d) =>
        (d.Kind == DateTimeKind.Unspecified ? DateTime.SpecifyKind(d, DateTimeKind.Utc) : d.ToUniversalTime()).ToString("o", CultureInfo.InvariantCulture);
    // Строки пишем в UTC с суффиксом «Z» (формат «o») — RoundtripKind вернёт DateTime с Kind=Utc.
    private static DateTime Time(string s) => DateTime.Parse(s, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind);
    private static Guid Uuid(SqliteDataReader r, int i) => Guid.Parse(r.GetString(i));
    private static Guid? UuidN(SqliteDataReader r, int i) => r.IsDBNull(i) ? null : Guid.Parse(r.GetString(i));
    private static double? DoubleN(SqliteDataReader r, int i) => r.IsDBNull(i) ? null : r.GetDouble(i);

    private const string Columns = "id,project_id,parent_id,created_at,title,contract_number,positions,margin_percent,template_name,file_name";
    private static QuotationInfo Info(SqliteDataReader r) => new(Uuid(r, 0), Uuid(r, 1), UuidN(r, 2),
        Time(r.GetString(3)), r.GetString(4), r.GetString(5), r.GetInt32(6), DoubleN(r, 7), r.GetString(8), r.GetString(9));

    public Task<IReadOnlyList<QuotationInfo>> ListAsync(string search, Guid? projectId, int offset, int limit, CancellationToken ct) => Run<IReadOnlyList<QuotationInfo>>(async db =>
    {
        await using var cmd = db.CreateCommand();
        cmd.CommandText = $"SELECT {Columns} FROM spec_quotations WHERE ($search='' OR instr(lower(title || ' ' || contract_number),lower($search))>0) AND ($project IS NULL OR project_id=$project) ORDER BY created_at DESC,id DESC LIMIT $limit OFFSET $offset";
        P(cmd, "$search", search); P(cmd, "$project", projectId?.ToString()); P(cmd, "$limit", limit); P(cmd, "$offset", offset);
        await using var r = await cmd.ExecuteReaderAsync(ct);
        var result = new List<QuotationInfo>();
        while (await r.ReadAsync(ct)) result.Add(Info((SqliteDataReader)r));
        return result;
    }, ct);

    public Task<QuotationDetail?> GetAsync(Guid id, CancellationToken ct) => Run(async db =>
    {
        await using var cmd = db.CreateCommand();
        cmd.CommandText = $"SELECT {Columns},snapshot FROM spec_quotations WHERE id=$id";
        P(cmd, "$id", id.ToString());
        await using var r = (SqliteDataReader)await cmd.ExecuteReaderAsync(ct);
        return await r.ReadAsync(ct) ? new QuotationDetail(Info(r), JsonSerializer.Deserialize<QuotationSnapshot>(r.GetString(10), Json)!) : null;
    }, ct);

    public Task<string?> GetRequestHashAsync(Guid id, CancellationToken ct) => Run(async db =>
    {
        await using var cmd = db.CreateCommand();
        cmd.CommandText = "SELECT request_hash FROM spec_quotations WHERE id=$id";
        P(cmd, "$id", id.ToString());
        return await cmd.ExecuteScalarAsync(ct) as string;
    }, ct);

    public Task<ExportedFile?> GetFileAsync(Guid id, CancellationToken ct) => Run(async db =>
    {
        await using var cmd = db.CreateCommand();
        cmd.CommandText = "SELECT content,file_name,content_type FROM spec_quotations WHERE id=$id";
        P(cmd, "$id", id.ToString());
        await using var r = (SqliteDataReader)await cmd.ExecuteReaderAsync(ct);
        return await r.ReadAsync(ct) ? new ExportedFile(r.GetFieldValue<byte[]>(0), r.GetString(1), r.GetString(2)) : null;
    }, ct);

    public Task InsertAsync(StoredQuotation q, CancellationToken ct) => Run(async db =>
    {
        await using var cmd = db.CreateCommand();
        cmd.CommandText = """
            INSERT INTO spec_quotations (id,project_id,parent_id,created_at,title,contract_number,positions,margin_percent,template_name,file_name,content_type,request_hash,snapshot,content)
            VALUES ($id,$project,$parent,$created,$title,$contract,$positions,$margin,$template,$file,$type,$hash,$snapshot,$content) ON CONFLICT(id) DO NOTHING
            """;
        var i = q.Info;
        P(cmd, "$id", i.Id.ToString()); P(cmd, "$project", i.ProjectId.ToString()); P(cmd, "$parent", i.ParentId?.ToString());
        P(cmd, "$created", Text(i.CreatedAt)); P(cmd, "$title", i.Title); P(cmd, "$contract", i.ContractNumber);
        P(cmd, "$positions", i.Positions); P(cmd, "$margin", i.MarginPercent); P(cmd, "$template", i.TemplateName);
        P(cmd, "$file", i.FileName); P(cmd, "$type", q.ContentType); P(cmd, "$hash", q.RequestHash);
        P(cmd, "$snapshot", JsonSerializer.Serialize(q.Snapshot, Json)); P(cmd, "$content", q.Content);
        return await cmd.ExecuteNonQueryAsync(ct);
    }, ct);

    public void Dispose() { connection?.Dispose(); gate.Dispose(); }
}
