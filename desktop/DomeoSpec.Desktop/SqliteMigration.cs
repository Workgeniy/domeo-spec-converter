using System.Globalization;
using Microsoft.Data.Sqlite;
using Npgsql;

namespace DomeoSpec.Desktop;

/// <summary>Разовый перенос истории КП, объектов и загрузок из портативного PostgreSQL в SQLite
/// при первом запуске версии со встроенным хранилищем. Тупое копирование колонок: JSON остаётся
/// текстом, bytea→BLOB, uuid/timestamptz→TEXT. Пишем во временный файл и по успеху переименовываем —
/// так наличие целевого .db означает «миграция прошла полностью», а оборванная попытка не оставляет
/// половинчатую базу. Исходный кластер PostgreSQL не трогаем (остаётся резервной копией).</summary>
internal static class SqliteMigration
{
    public static void Migrate(string pgConnectionString, string sqlitePath)
    {
        var tmp = sqlitePath + ".migrating";
        if (File.Exists(tmp)) File.Delete(tmp);
        try
        {
            using (var pg = new NpgsqlConnection(pgConnectionString))
            using (var lite = new SqliteConnection(new SqliteConnectionStringBuilder
                       { DataSource = tmp, Mode = SqliteOpenMode.ReadWriteCreate, Pooling = false }.ConnectionString))
            {
                pg.Open();
                lite.Open();
                CreateSchema(lite);
                using var tx = lite.BeginTransaction();
                Copy(pg, lite, tx, "spec_projects",
                    "SELECT id,revision,updated_at,title,documents,positions,margin_percent,quotation_id,mutation_id,request_hash,snapshot::text FROM spec_projects");
                Copy(pg, lite, tx, "spec_uploads",
                    "SELECT id,project_id,created_at,file_name,title,size,sha256,content_type,content,document::text,error FROM spec_uploads");
                Copy(pg, lite, tx, "spec_quotations",
                    "SELECT id,project_id,parent_id,created_at,title,contract_number,positions,margin_percent,template_name,file_name,content_type,request_hash,snapshot::text,content FROM spec_quotations");
                tx.Commit();
            }
            SqliteConnection.ClearAllPools();  // отпускаем файл, чтобы переименовать
            File.Move(tmp, sqlitePath);
        }
        catch
        {
            SqliteConnection.ClearAllPools();
            try { if (File.Exists(tmp)) File.Delete(tmp); } catch { }
            throw;  // неуспех переносим на следующий запуск; целевого .db нет — исходные данные целы
        }
    }

    // Колонки INSERT берём из набора source — имена совпадают с колонками таблицы SQLite.
    private static void Copy(NpgsqlConnection pg, SqliteConnection lite, SqliteTransaction tx, string table, string selectSql)
    {
        using var read = new NpgsqlCommand(selectSql, pg);
        using var r = read.ExecuteReader();
        var cols = Enumerable.Range(0, r.FieldCount).Select(r.GetName).ToArray();
        var insertSql = $"INSERT INTO {table} ({string.Join(",", cols)}) VALUES ({string.Join(",", cols.Select((_, i) => "$p" + i))})";
        while (r.Read())
        {
            using var ins = lite.CreateCommand();
            ins.Transaction = tx;
            ins.CommandText = insertSql;
            for (var i = 0; i < cols.Length; i++)
                ins.Parameters.AddWithValue("$p" + i, ToSqlite(r.GetValue(i)));
            ins.ExecuteNonQuery();
        }
    }

    private static object ToSqlite(object value) => value switch
    {
        DBNull => DBNull.Value,
        Guid g => g.ToString(),
        DateTime d => (d.Kind == DateTimeKind.Unspecified ? DateTime.SpecifyKind(d, DateTimeKind.Utc) : d.ToUniversalTime())
            .ToString("o", CultureInfo.InvariantCulture),
        _ => value,  // string (в т.ч. JSON как текст), byte[] (→BLOB), int/long/double
    };

    // ВАЖНО: должно совпадать со схемой в SqliteQuotationStore.EnsureSchema (api).
    private static void CreateSchema(SqliteConnection db)
    {
        using var cmd = db.CreateCommand();
        cmd.CommandText = """
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
        cmd.ExecuteNonQuery();
    }
}
