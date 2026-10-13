using System.Collections.Concurrent;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;
using DomeoSpec.Application.Parsing;
using DomeoSpec.Application.Uploads;
using DomeoSpec.Domain.Specifications;
using DomeoSpec.Domain.Uploads;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
namespace DomeoSpec.Api.Tests;
public sealed class UploadsApiTests
{
    private const string Url="/api/specifications/uploads";
    [Theory]
    [InlineData("чертёж.pdf")] [InlineData("перечень.xlsx")] [InlineData("перечень.xlsm")]
    public async Task Original_saved_before_parse_survives_engine_failure_and_retry(string name)
    {
        using var factory=new ApiFactory(); var store=new MemoryUploads();
        using var app=factory.WithWebHostBuilder(b=>b.ConfigureServices(s=>{ s.RemoveAll<IUploadStore>();s.AddSingleton<IUploadStore>(store); }));
        using var client=app.CreateClient();
        var project=Guid.NewGuid();
        var content=new byte[] {10,20,30,40};
        factory.Engine.Down=true;
        var response=await client.PostAsync(Url,Form(project,name,content));
        Assert.Equal(HttpStatusCode.OK,response.StatusCode);
        var id=(await response.Content.ReadFromJsonAsync<JsonNode>())!["data"]!["id"]!.GetValue<Guid>();
        Assert.Equal(content,await client.GetByteArrayAsync($"{Url}/{id}/file"));
        Assert.Equal(HttpStatusCode.ServiceUnavailable,(await client.PostAsync($"{Url}/{id}/parse",null)).StatusCode);
        Assert.NotNull(store.Rows[id].Detail.Info.Error);
        Assert.Equal(content,await client.GetByteArrayAsync($"{Url}/{id}/file"));
        var retry=await client.PostAsync(Url,Form(project,name,content));
        Assert.Equal(id,(await retry.Content.ReadFromJsonAsync<JsonNode>())!["data"]!["id"]!.GetValue<Guid>());
        Assert.Single(store.Rows);
        factory.Engine.Down=false;
        Assert.Equal(HttpStatusCode.OK,(await client.PostAsync($"{Url}/{id}/parse",null)).StatusCode);
        factory.Engine.Down=true;
        // Готовый результат открывается и без ядра, с другого HTTP-клиента.
        using var second=app.CreateClient();
        Assert.Equal(HttpStatusCode.OK,(await second.PostAsync($"{Url}/{id}/parse",null)).StatusCode);
        var detail=await second.GetFromJsonAsync<JsonNode>($"{Url}/{id}");
        Assert.Equal(name,detail!["data"]!["document"]!["file_name"]!.GetValue<string>());
        Assert.True(detail["data"]!["info"]!["parsed"]!.GetValue<bool>());
        Assert.Null(detail["data"]!["info"]!["error"]);
        var list=await second.GetFromJsonAsync<JsonNode>(Url);
        Assert.Single(list!["data"]!.AsArray());Assert.Null(list["data"]![0]!["document"]);
        await client.PostAsync(Url,Form(project,name,[99]));
        Assert.Equal(2,store.Rows.Count); // Новые байты с прежним именем не затирают оригинал.
    }
    [Theory]
    [InlineData("file.exe",1)] [InlineData("file.pdf",0)]
    public async Task Rejects_invalid_upload_without_saving(string name,int length)
    {
        using var factory=new ApiFactory();var store=new MemoryUploads();
        using var app=factory.WithWebHostBuilder(b=>b.ConfigureServices(s=>{s.RemoveAll<IUploadStore>();s.AddSingleton<IUploadStore>(store);}));
        using var client=app.CreateClient();
        Assert.Equal(HttpStatusCode.BadRequest,(await client.PostAsync(Url,Form(Guid.NewGuid(),name,new byte[length]))).StatusCode);
        Assert.Empty(store.Rows);
        Assert.Equal(HttpStatusCode.BadRequest,(await client.GetAsync(Url+"?offset=-1")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound,(await client.GetAsync($"{Url}/{Guid.NewGuid()}" )).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound,(await client.GetAsync($"{Url}/{Guid.NewGuid()}/file" )).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound,(await client.PostAsync($"{Url}/{Guid.NewGuid()}/parse",null)).StatusCode);
    }
    [Fact]
    public async Task Quote_references_archived_source_without_copying_bytes()
    {
        using var factory=new ApiFactory();var uploads=new MemoryUploads();var quotes=new MemoryQuotations();
        using var app=factory.WithWebHostBuilder(b=>b.ConfigureServices(s=>{
            s.RemoveAll<IUploadStore>();s.AddSingleton<IUploadStore>(uploads);
            s.RemoveAll<DomeoSpec.Application.Quotations.IQuotationStore>();s.AddSingleton<DomeoSpec.Application.Quotations.IQuotationStore>(quotes);
        }));
        using var client=app.CreateClient();var request=QuotationsApiTests.Request();
        var saved=await client.PostAsync(Url,Form(request.ProjectId,"план.pdf",[1,2,3]));
        var id=(await saved.Content.ReadFromJsonAsync<JsonNode>())!["data"]!["id"]!.GetValue<Guid>();
        request=request with {Snapshot=request.Snapshot with {Documents=[request.Snapshot.Documents[0] with {
            Original=new DomeoSpec.Domain.Quotations.QuotationSource(id.ToString(),"план.pdf","",UploadId:id)
        }]}};
        var json=new JsonSerializerOptions {PropertyNamingPolicy=JsonNamingPolicy.SnakeCaseLower};
        Assert.Equal(HttpStatusCode.OK,(await client.PostAsJsonAsync("/api/specifications/quotations",request,json)).StatusCode);
        Assert.Equal(id,quotes.Rows[request.Id].Snapshot.Documents[0].Original!.UploadId);
        Assert.Empty(quotes.Rows[request.Id].Snapshot.Documents[0].Original!.Content);
        uploads.Rows.Clear();
        Assert.Equal(HttpStatusCode.BadRequest,(await client.PostAsJsonAsync("/api/specifications/quotations",request with {Id=Guid.NewGuid()},json)).StatusCode);
    }
    private static MultipartFormDataContent Form(Guid project,string name,byte[] content)
    {
        var form=new MultipartFormDataContent();form.Add(new ByteArrayContent(content),"file",name);
        form.Add(new StringContent(project.ToString()),"projectId");return form;
    }
}
internal sealed class MemoryUploads : IUploadStore
{
    internal sealed record Row(UploadDetail Detail,ExportedFile File);
    public ConcurrentDictionary<Guid,Row> Rows { get; }=new();
    public Task<UploadInfo> SaveUploadAsync(UploadInfo info,byte[] content,string type,CancellationToken ct)
    {
        var found=Rows.Values.FirstOrDefault(r=>r.Detail.Info.ProjectId==info.ProjectId && r.Detail.Info.FileName==info.FileName && r.Detail.Info.Sha256==info.Sha256);
        if(found is not null)return Task.FromResult(found.Detail.Info);
        Rows[info.Id]=new(new(info,null),new(content,info.FileName,type));return Task.FromResult(info);
    }
    public Task<IReadOnlyList<UploadInfo>> ListUploadsAsync(string search,int offset,int limit,CancellationToken ct)
        =>Task.FromResult<IReadOnlyList<UploadInfo>>(Rows.Values.Select(r=>r.Detail.Info).Where(i=>(i.Title+i.FileName).Contains(search)).Skip(offset).Take(limit).ToArray());
    public Task<UploadDetail?> GetUploadAsync(Guid id,CancellationToken ct)=>Task.FromResult(Rows.TryGetValue(id,out var r)?r.Detail:null);
    public Task<ExportedFile?> GetUploadFileAsync(Guid id,CancellationToken ct)=>Task.FromResult(Rows.TryGetValue(id,out var r)?r.File:null);
    public Task SetUploadResultAsync(Guid id,ParsedDocument? document,string? error,CancellationToken ct)
    { var r=Rows[id];if(r.Detail.Document is null)Rows[id]=r with {Detail=new(r.Detail.Info with {Parsed=document is not null,Error=error},document)};return Task.CompletedTask; }
}
