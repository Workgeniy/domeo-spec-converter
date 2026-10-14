using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;
using DomeoSpec.Application.Common;
using DomeoSpec.Application.Parsing;
using DomeoSpec.Domain.Quotations;
using DomeoSpec.Domain.Specifications;
using DomeoSpec.Domain.Uploads;
using DomeoSpec.Infrastructure.Quotations;
using Microsoft.AspNetCore.Hosting;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Hosting;
namespace DomeoSpec.Api.Tests;

// Проверяют реальный SQL встроенного хранилища на временном файле — без внешней БД (в отличие от
// [PostgresFact]), поэтому идут в обычном прогоне. Каждый тест — свой файл; соединение одно, без пула.
public sealed class SqliteStoreTests : IDisposable
{
    private readonly string dir = Path.Combine(Path.GetTempPath(), "domeo-sqlite-tests", Guid.NewGuid().ToString("N"));
    private IConfiguration Config() => new ConfigurationBuilder()
        .AddInMemoryCollection(new Dictionary<string, string?> { ["ConnectionStrings:Quotations"] = $"Data Source={Path.Combine(dir, "domeo.db")}" }).Build();
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    public SqliteStoreTests() => Directory.CreateDirectory(dir);
    public void Dispose() { SqliteConnection.ClearAllPools(); try { Directory.Delete(dir, true); } catch { } }

    [Fact]
    public async Task Api_selects_sqlite_by_connection_string_and_serves_over_http()
    {
        var dbPath = Path.Combine(dir, "api.db");
        using var factory = new ApiFactory();
        // «Data Source=…» без Host= → DI выбирает встроенный SQLite (как в десктопе).
        using var app = factory.WithWebHostBuilder(b => b.UseSetting("ConnectionStrings:Quotations", $"Data Source={dbPath}"));
        using var client = app.CreateClient();
        var url = $"/api/specifications/projects/{Guid.NewGuid()}";
        Assert.Equal(HttpStatusCode.OK, (await client.PutAsJsonAsync(url, ProjectsApiTests.Request(), Json)).StatusCode);
        var detail = (await client.GetFromJsonAsync<JsonNode>(url))!["data"]!;
        Assert.Equal(1, detail["info"]!["revision"]!.GetValue<int>());
        Assert.True(detail["snapshot"]!["documents"]![0]!["doc"]!["summary"]![1]!["excluded"]!.GetValue<bool>());
        var listed = (await client.GetFromJsonAsync<JsonNode>("/api/specifications/projects?search=Школа"))!["data"]!.AsArray();
        Assert.Single(listed);
        Assert.True(File.Exists(dbPath));  // DI действительно выбрал SQLite — файл создан
    }

    [Fact]
    public async Task Projects_serialize_writers_retries_and_survive_restart()
    {
        var config = Config();
        var id = Guid.NewGuid();
        var request = ProjectsApiTests.Request();
        using (var store = new SqliteQuotationStore(config))
        {
            // Параллельные повторы с тем же mutation_id идемпотентны — все видят ревизию 1.
            var retries = await Task.WhenAll(Enumerable.Range(0, 4).Select(_ => store.SaveProjectAsync(id, request, "same", default)));
            Assert.All(retries, x => Assert.Equal(1, x.Revision));
            // Тот же mutation_id, но другой запрос — конфликт, а не тихая перезапись.
            await Assert.ThrowsAsync<ConflictException>(() => store.SaveProjectAsync(id, request, "different", default));
            async Task<bool> Update(string label)
            {
                try { await store.SaveProjectAsync(id, ProjectsApiTests.Request(1) with { Snapshot = request.Snapshot with { Title = label } }, label, default); return true; }
                catch (ConflictException) { return false; }
            }
            var writers = await Task.WhenAll(Update("А"), Update("Б"));
            Assert.Single(writers, x => x);  // ровно один писатель с ревизии 1 проходит
        }
        using (var store = new SqliteQuotationStore(config))  // новый экземпляр = перезапуск процесса
        {
            var reopened = (await store.GetProjectAsync(id, default))!;
            Assert.Equal(2, reopened.Info.Revision);
            Assert.True(reopened.Snapshot.Documents[0].Doc.Summary[1].Excluded);
            Assert.Equal(10, reopened.Snapshot.Indexation.Rates["Мебель IKEA"]);
            Assert.Equal("c2FtcGxl", reopened.Snapshot.Template);
            await Assert.ThrowsAsync<ConflictException>(() => store.SaveProjectAsync(id, request, "same", default));
            Assert.Contains(await store.ListProjectsAsync(reopened.Info.Title, 0, 100, default), p => p.Id == id);
            Assert.Empty(await store.ListProjectsAsync("", 1, 100, default));  // пагинация: страница за пределами пуста
            var empty = await store.SaveProjectAsync(id, ProjectsApiTests.Request(2) with { Snapshot = request.Snapshot with { Documents = [] } }, "empty", default);
            Assert.Equal(0, empty.Documents); Assert.Equal(3, empty.Revision);
            Assert.Null(await store.GetProjectAsync(Guid.NewGuid(), default));
        }
    }

    [Fact]
    public async Task Project_title_falls_back_to_document_name_and_search_is_unicode_insensitive()
    {
        using var store = new SqliteQuotationStore(Config());
        // Заголовок пуст → в списке показываем имя документа первого тома (file_name) через json_extract.
        var noTitle = Guid.NewGuid();
        await store.SaveProjectAsync(noTitle, ProjectsApiTests.Request() with { Snapshot = NamedSnapshot("") }, "a", default);
        var listed = await store.ListProjectsAsync("", 0, 100, default);
        Assert.Equal("spec.xlsx", listed.Single(p => p.Id == noTitle).Title);
        Assert.Contains(await store.ListProjectsAsync("spec", 0, 100, default), p => p.Id == noTitle);  // поиск по подставленному имени
        // Регистронезависимый поиск по кириллице (встроенный lower в SQLite знает только ASCII — заменён).
        var titled = Guid.NewGuid();
        await store.SaveProjectAsync(titled, ProjectsApiTests.Request() with { Snapshot = NamedSnapshot("Школа №7") }, "b", default);
        Assert.Contains(await store.ListProjectsAsync("школа", 0, 100, default), p => p.Id == titled);
    }

    [Fact]
    public async Task Quotations_persist_dedupe_and_page()
    {
        var config = Config();
        var req = QuotationsApiTests.Request();
        var info = new QuotationInfo(req.Id, req.ProjectId, null, DateTime.UtcNow, "Тест ' SQL", "42", 1, 20, "Моя форма", "test.xlsx");
        var q = new StoredQuotation(info, req.Snapshot, "hash", [5, 6, 7], "application/xlsx");
        using (var store = new SqliteQuotationStore(config))
        {
            await Task.WhenAll(Enumerable.Range(0, 5).Select(_ => store.InsertAsync(q, default)));  // ON CONFLICT DO NOTHING
            Assert.Single(await store.ListAsync("' SQL", req.ProjectId, 0, 30, default));  // кавычка — не инъекция (параметр)
        }
        using (var store = new SqliteQuotationStore(config))
        {
            var detail = await store.GetAsync(req.Id, default);
            Assert.Equal(20, detail!.Snapshot.Kp.MarginPercent);
            Assert.True(detail.Snapshot.Documents[0].Doc.Summary[1].Excluded);
            Assert.Equal(10, detail.Snapshot.Indexation.Rates["Мебель IKEA"]);
            Assert.Equal(new byte[] { 5, 6, 7 }, (await store.GetFileAsync(req.Id, default))!.Content);
            Assert.Equal("hash", await store.GetRequestHashAsync(req.Id, default));
            Assert.Empty(await store.ListAsync("", req.ProjectId, 1, 30, default));  // вторая страница пуста
            Assert.Null(await store.GetAsync(Guid.NewGuid(), default));
        }
    }

    [Fact]
    public async Task Uploads_dedupe_in_parallel_and_result_is_not_overwritten()
    {
        var config = Config();
        var project = Guid.NewGuid();
        var info = new UploadInfo(Guid.NewGuid(), project, DateTime.UtcNow, "Тестовый план.pdf", "Тест оригинала", 3, "ABC", false, null);
        Guid savedId;
        using (var store = new SqliteQuotationStore(config))
        {
            var results = await Task.WhenAll(Enumerable.Range(0, 4).Select(_ => store.SaveUploadAsync(info with { Id = Guid.NewGuid() }, [5, 6, 7], "application/pdf", default)));
            savedId = results[0].Id;
            Assert.All(results, r => Assert.Equal(savedId, r.Id));  // одинаковый (project,file,sha) → одна запись
            await store.SetUploadResultAsync(savedId, null, "Ядро недоступно", default);
        }
        using (var store = new SqliteQuotationStore(config))
        {
            Assert.Equal(new byte[] { 5, 6, 7 }, (await store.GetUploadFileAsync(savedId, default))!.Content);
            Assert.Equal("Ядро недоступно", (await store.GetUploadAsync(savedId, default))!.Info.Error);
            await store.SetUploadResultAsync(savedId, new ParsedDocument { FileName = info.FileName, Title = "Объект", Summary = [new SummaryItem { Name = "Стол" }] }, null, default);
            await store.SetUploadResultAsync(savedId, null, "Поздняя ошибка", default);  // успех не затирается
            var detail = await store.GetUploadAsync(savedId, default);
            Assert.True(detail!.Info.Parsed); Assert.Null(detail.Info.Error); Assert.Equal("Стол", detail.Document!.Summary[0].Name);
            Assert.Single(await store.ListUploadsAsync("Тестовый план", 0, 100, default), r => r.ProjectId == project);
        }
    }

    [Fact]
    public async Task Missing_connection_string_reports_unavailable()
    {
        var empty = new ConfigurationBuilder().Build();
        using var store = new SqliteQuotationStore(empty);
        await Assert.ThrowsAsync<ServiceUnavailableException>(() => store.ListProjectsAsync("", 0, 10, default));
    }

    // Снимок с заданным заголовком и документом (file_name = spec.xlsx), остальное — из общего образца.
    private static QuotationSnapshot NamedSnapshot(string title) => ProjectsApiTests.Request().Snapshot with { Title = title };
}
