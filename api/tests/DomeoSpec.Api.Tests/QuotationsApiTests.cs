using System.Collections.Concurrent;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;
using DomeoSpec.Application.Quotations;
using DomeoSpec.Application.Parsing;
using DomeoSpec.Domain.Quotations;
using DomeoSpec.Domain.Specifications;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace DomeoSpec.Api.Tests;
public sealed class QuotationsApiTests
{
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    internal static SaveQuotation Request(Guid? project = null, Guid? parent = null, double? margin = 20) => new(Guid.NewGuid(),project ?? Guid.NewGuid(),parent,new QuotationSnapshot
    {
        Title="Школа №1", Kp=new KpSettings { MarginPercent=margin, MarkupPercent=90, ContractNumber="42" },
        Indexation=new Indexation { BaseDate="2026-10-09", Date="2027-10-09", ApplyToKp=true, Rates=new Dictionary<string,double> { ["Мебель IKEA"]=10 } },
        TemplateName="Своя форма", Template="c2FtcGxl",
        Documents=[new QuotationDocument("doc1","2026-10-09",new ParsedDocument {
            FileName="spec.xlsx", Summary=[new SummaryItem { Name="Стол",Price=100,Qty=2 },new SummaryItem { Name="Исключён",Price=500,Qty=1,Excluded=true }]
        },new QuotationSource("file1","spec.xlsx","c291cmNl"))]
    });
    [Fact]
    public async Task Save_reopen_download_new_version_and_retry_are_lossless()
    {
        using var factory=new ApiFactory();
        var store=new MemoryQuotations();
        using var app=factory.WithWebHostBuilder(b=>b.ConfigureServices(s=> { s.RemoveAll<IQuotationStore>();s.AddSingleton<IQuotationStore>(store); }));
        using var client=app.CreateClient();
        var request=Request();
        var response=await client.PostAsJsonAsync("/api/specifications/quotations",request,Json);
        Assert.Equal(HttpStatusCode.OK,response.StatusCode);
        Assert.Single(factory.Engine.LastExported!.Summary);
        Assert.Equal(20,factory.Engine.LastExported.Kp!.MarginPercent);
        Assert.Equal("c2FtcGxl",factory.Engine.LastExported.KpTemplate);
        Assert.Equal("2026-10-09",factory.Engine.LastExported.Indexation!.BaseDate);
        Assert.Equal(HttpStatusCode.OK,(await client.PostAsJsonAsync("/api/specifications/quotations",request,Json)).StatusCode);
        Assert.Single(store.Rows);
        var reopened=await client.GetFromJsonAsync<JsonNode>($"/api/specifications/quotations/{request.Id}");
        Assert.True(reopened!["data"]!["snapshot"]!["documents"]![0]!["doc"]!["summary"]![1]!["excluded"]!.GetValue<bool>());
        Assert.Equal(10,reopened["data"]!["snapshot"]!["indexation"]!["rates"]!["Мебель IKEA"]!.GetValue<double>());
        Assert.Equal("c291cmNl",reopened["data"]!["snapshot"]!["documents"]![0]!["original"]!["content"]!.GetValue<string>());
        var file=await client.GetByteArrayAsync($"/api/specifications/quotations/{request.Id}/file");
        Assert.Equal(new byte[] {1,2,3},file);
        var changed=request with { Id=Guid.NewGuid(),ParentId=request.Id,Snapshot=request.Snapshot with { Kp=request.Snapshot.Kp with { MarginPercent=30 } } };
        Assert.Equal(HttpStatusCode.OK,(await client.PostAsJsonAsync("/api/specifications/quotations",changed,Json)).StatusCode);
        Assert.Equal(2,store.Rows.Count);
        Assert.Equal(20,store.Rows[request.Id].Snapshot.Kp.MarginPercent);
        Assert.Equal(HttpStatusCode.BadRequest,(await client.PostAsJsonAsync("/api/specifications/quotations",changed with { Id=request.Id },Json)).StatusCode);
        var listed=await client.GetFromJsonAsync<JsonNode>($"/api/specifications/quotations?search=Школа&projectId={request.ProjectId}");
        Assert.Equal(2,listed!["data"]!.AsArray().Count);
        Assert.Null(listed["data"]![0]!["snapshot"]);
        Assert.Equal(HttpStatusCode.NotFound,(await client.GetAsync($"/api/specifications/quotations/{Guid.NewGuid()}")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound,(await client.GetAsync($"/api/specifications/quotations/{Guid.NewGuid()}/file")).StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest,(await client.GetAsync("/api/specifications/quotations?limit=101")).StatusCode);
        factory.Engine.Down=true;
        Assert.Equal(HttpStatusCode.ServiceUnavailable,(await client.PostAsJsonAsync("/api/specifications/quotations",Request(),Json)).StatusCode);
        Assert.Equal(2,store.Rows.Count);
        Assert.Equal(file,await client.GetByteArrayAsync($"/api/specifications/quotations/{request.Id}/file"));
    }
    [Theory]
    [InlineData(-1)] [InlineData(100)] [InlineData(150)]
    public async Task Invalid_margin_does_not_generate_or_save(double margin)
    {
        using var factory=new ApiFactory();var store=new MemoryQuotations();
        using var app=factory.WithWebHostBuilder(b=>b.ConfigureServices(s=> {s.RemoveAll<IQuotationStore>();s.AddSingleton<IQuotationStore>(store);}));
        using var client=app.CreateClient();
        Assert.Equal(HttpStatusCode.BadRequest,(await client.PostAsJsonAsync("/api/specifications/quotations",Request(margin:margin),Json)).StatusCode);
        Assert.Null(factory.Engine.LastExported);Assert.Empty(store.Rows);
    }
    [Fact]
    public async Task Empty_and_cross_project_parent_are_rejected()
    {
        using var factory=new ApiFactory();var store=new MemoryQuotations();
        using var app=factory.WithWebHostBuilder(b=>b.ConfigureServices(s=> {s.RemoveAll<IQuotationStore>();s.AddSingleton<IQuotationStore>(store);}));
        using var client=app.CreateClient();var request=Request();
        await client.PostAsJsonAsync("/api/specifications/quotations",request,Json);
        Assert.Equal(HttpStatusCode.BadRequest,(await client.PostAsJsonAsync("/api/specifications/quotations",Request(parent:request.Id),Json)).StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest,(await client.PostAsJsonAsync("/api/specifications/quotations",Request() with { Snapshot=new QuotationSnapshot() },Json)).StatusCode);
        Assert.Single(store.Rows);
    }
}
internal sealed class MemoryQuotations : IQuotationStore
{
    public ConcurrentDictionary<Guid,StoredQuotation> Rows { get; } = new();
    public Task<IReadOnlyList<QuotationInfo>> ListAsync(string search,Guid? projectId,int offset,int limit,CancellationToken ct) => Task.FromResult<IReadOnlyList<QuotationInfo>>(Rows.Values.Select(q=>q.Info).Where(q=>(projectId==null||q.ProjectId==projectId)&&(q.Title+q.ContractNumber).Contains(search)).OrderByDescending(q=>q.CreatedAt).Skip(offset).Take(limit).ToArray());
    public Task<QuotationDetail?> GetAsync(Guid id,CancellationToken ct) => Task.FromResult(Rows.TryGetValue(id,out var q)?new QuotationDetail(q.Info,q.Snapshot):null);
    public Task<string?> GetRequestHashAsync(Guid id,CancellationToken ct) => Task.FromResult(Rows.TryGetValue(id,out var q)?q.RequestHash:null);
    public Task<ExportedFile?> GetFileAsync(Guid id,CancellationToken ct) => Task.FromResult(Rows.TryGetValue(id,out var q)?new ExportedFile(q.Content,q.Info.FileName,q.ContentType):null);
    public Task InsertAsync(StoredQuotation q,CancellationToken ct) {Rows.TryAdd(q.Info.Id,q);return Task.CompletedTask;}
}
