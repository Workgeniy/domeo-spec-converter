using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;
using DomeoSpec.Application.Common;
using DomeoSpec.Application.Quotations;
using DomeoSpec.Domain.Quotations;
using DomeoSpec.Infrastructure.Quotations;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Npgsql;
namespace DomeoSpec.Api.Tests;

public sealed class ProjectsApiTests
{
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    internal static SaveProject Request(long revision = 0) => new(revision, Guid.NewGuid(), QuotationsApiTests.Request().Snapshot with {
        Documents = QuotationsApiTests.Request().Snapshot.Documents.Select(d => d with { Original = null }).ToArray()
    });

    [Fact]
    public async Task Endpoints_preserve_work_without_export_and_report_conflict()
    {
        using var factory = new ApiFactory(); var store = new MemoryProjects();
        using var app = factory.WithWebHostBuilder(b => b.ConfigureServices(s => { s.RemoveAll<IProjectStore>(); s.AddSingleton<IProjectStore>(store); }));
        using var client = app.CreateClient();
        var id = Guid.NewGuid(); var request = Request(); var url = $"/api/specifications/projects/{id}";
        Assert.Equal(HttpStatusCode.OK, (await client.PutAsJsonAsync(url, request, Json)).StatusCode);
        Assert.Null(factory.Engine.LastExported);
        var detail = (await client.GetFromJsonAsync<JsonNode>(url))!["data"]!;
        Assert.Equal(1, detail["info"]!["revision"]!.GetValue<int>());
        Assert.True(detail["snapshot"]!["documents"]![0]!["doc"]!["summary"]![1]!["excluded"]!.GetValue<bool>());
        Assert.Equal(20, detail["snapshot"]!["kp"]!["margin_percent"]!.GetValue<int>());
        Assert.Equal(10, detail["snapshot"]!["indexation"]!["rates"]!["Мебель IKEA"]!.GetValue<int>());
        Assert.Equal(HttpStatusCode.OK, (await client.PutAsJsonAsync(url, request, Json)).StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, (await client.PutAsJsonAsync(url, Request(), Json)).StatusCode);
        var changed = request with { ExpectedRevision = 1, MutationId = Guid.NewGuid(), Snapshot = request.Snapshot with { Title = "Новый заголовок", Documents = [] } };
        Assert.Equal(HttpStatusCode.OK, (await client.PutAsJsonAsync(url, changed, Json)).StatusCode);
        var listed = (await client.GetFromJsonAsync<JsonNode>("/api/specifications/projects?search=Новый"))!["data"]!.AsArray();
        Assert.Single(listed); Assert.Null(listed[0]!["snapshot"]);
        Assert.Equal(0, listed[0]!["documents"]!.GetValue<int>());
        Assert.Equal(HttpStatusCode.BadRequest, (await client.GetAsync("/api/specifications/projects?limit=101")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await client.GetAsync($"/api/specifications/projects/{Guid.NewGuid()}")).StatusCode);
    }

    [Fact]
    public async Task Invalid_snapshot_and_original_are_rejected()
    {
        using var factory = new ApiFactory(); var store = new MemoryProjects();
        using var app = factory.WithWebHostBuilder(b => b.ConfigureServices(s => { s.RemoveAll<IProjectStore>(); s.AddSingleton<IProjectStore>(store); }));
        using var client = app.CreateClient(); var url = $"/api/specifications/projects/{Guid.NewGuid()}";
        var request = Request();
        foreach (var invalid in new[] {
            request with { ExpectedRevision = -1 }, request with { MutationId = Guid.Empty },
            request with { Snapshot = null! }, request with { Snapshot = request.Snapshot with { Version = 2 } },
            request with { Snapshot = request.Snapshot with { Kp = request.Snapshot.Kp with { MarginPercent = 100 } } },
            request with { Snapshot = QuotationsApiTests.Request().Snapshot }
        }) Assert.Equal(HttpStatusCode.BadRequest, (await client.PutAsJsonAsync(url, invalid, Json)).StatusCode);
        Assert.Empty(store.Rows);
    }

    [PostgresFact]
    public async Task Real_database_serializes_writers_retries_and_survives_restart()
    {
        var connection = Environment.GetEnvironmentVariable("TEST_QUOTATIONS_CONNECTION")!;
        var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["ConnectionStrings:Quotations"] = connection }).Build();
        var id = Guid.NewGuid(); var request = Request();
        try
        {
            using (var store = new PostgresQuotationStore(config))
            {
                var retries = await Task.WhenAll(Enumerable.Range(0, 4).Select(_ => store.SaveProjectAsync(id, request, "same", default)));
                Assert.All(retries, x => Assert.Equal(1, x.Revision));
                await Assert.ThrowsAsync<ConflictException>(() => store.SaveProjectAsync(id, request, "different", default));
                async Task<bool> Update(string label)
                {
                    try { await store.SaveProjectAsync(id, Request(1) with { Snapshot = request.Snapshot with { Title = label } }, label, default); return true; }
                    catch (ConflictException) { return false; }
                }
                var writers = await Task.WhenAll(Update("А"), Update("Б"));
                Assert.Single(writers, x => x);
            }
            using (var store = new PostgresQuotationStore(config))
            {
                var reopened = (await store.GetProjectAsync(id, default))!;
                Assert.Equal(2, reopened.Info.Revision);
                Assert.True(reopened.Snapshot.Documents[0].Doc.Summary[1].Excluded);
                Assert.Equal(10, reopened.Snapshot.Indexation.Rates["Мебель IKEA"]);
                Assert.Equal("c2FtcGxl", reopened.Snapshot.Template);
                await Assert.ThrowsAsync<ConflictException>(() => store.SaveProjectAsync(id, request, "same", default));
                Assert.Contains(await store.ListProjectsAsync(reopened.Info.Title, 0, 100, default), p => p.Id == id);
                var empty = await store.SaveProjectAsync(id, Request(2) with { Snapshot = request.Snapshot with { Documents = [] } }, "empty", default);
                Assert.Equal(0, empty.Documents); Assert.Equal(3, empty.Revision);
            }
        }
        finally
        {
            await using var db = new NpgsqlConnection(connection); await db.OpenAsync();
            await using var command = new NpgsqlCommand("DELETE FROM spec_projects WHERE id=$1", db);
            command.Parameters.AddWithValue(id); await command.ExecuteNonQueryAsync();
        }
    }
}

internal sealed class MemoryProjects : IProjectStore
{
    public Dictionary<Guid, (ProjectDetail Detail, Guid Mutation, string Hash)> Rows { get; } = new();
    public Task<IReadOnlyList<ProjectInfo>> ListProjectsAsync(string search, int offset, int limit, CancellationToken ct)
        => Task.FromResult<IReadOnlyList<ProjectInfo>>(Rows.Values.Select(v => v.Detail.Info).Where(v => v.Title.Contains(search)).Skip(offset).Take(limit).ToArray());
    public Task<ProjectDetail?> GetProjectAsync(Guid id, CancellationToken ct) => Task.FromResult(Rows.TryGetValue(id, out var v) ? v.Detail : null);
    public Task<ProjectInfo> SaveProjectAsync(Guid id, SaveProject request, string hash, CancellationToken ct)
    {
        lock (Rows)
        {
            Rows.TryGetValue(id, out var current);
            if (current.Mutation == request.MutationId && current.Hash == hash) return Task.FromResult(current.Detail.Info);
            if ((current.Detail?.Info.Revision ?? 0) != request.ExpectedRevision) throw new ConflictException("Объект изменён.");
            var s = request.Snapshot;
            var info = new ProjectInfo(id, request.ExpectedRevision + 1, DateTime.UtcNow, s.Title, s.Documents.Count,
                s.Documents.Sum(d => d.Doc.Summary.Count(r => !r.Excluded)), s.Kp.MarginPercent, request.QuotationId);
            Rows[id] = (new ProjectDetail(info, s), request.MutationId, hash);
            return Task.FromResult(info);
        }
    }
}
