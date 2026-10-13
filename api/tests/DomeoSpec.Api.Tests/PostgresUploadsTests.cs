using DomeoSpec.Domain.Specifications;
using DomeoSpec.Domain.Uploads;
using DomeoSpec.Infrastructure.Quotations;
using Microsoft.Extensions.Configuration;
using Npgsql;
namespace DomeoSpec.Api.Tests;
public sealed class PostgresUploadsTests
{
    [PostgresFact]
    public async Task Original_persists_and_parallel_retries_deduplicate_without_overwriting()
    {
        var connection=Environment.GetEnvironmentVariable("TEST_QUOTATIONS_CONNECTION")!;
        var config=new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string,string?>{["ConnectionStrings:Quotations"]=connection}).Build();
        var project=Guid.NewGuid();var info=new UploadInfo(Guid.NewGuid(),project,DateTime.UtcNow,"Тестовый план.pdf","Тест оригинала",3,"ABC",false,null);
        Guid savedId=default;
        try
        {
            using(var store=new PostgresQuotationStore(config))
            {
                var results=await Task.WhenAll(Enumerable.Range(0,4).Select(_=>store.SaveUploadAsync(info with{Id=Guid.NewGuid()},[5,6,7],"application/pdf",default)));
                savedId=results[0].Id;Assert.All(results,r=>Assert.Equal(savedId,r.Id));
                await store.SetUploadResultAsync(savedId,null,"Ядро недоступно",default);
            }
            using(var store=new PostgresQuotationStore(config))
            {
                Assert.Equal(new byte[]{5,6,7},(await store.GetUploadFileAsync(savedId,default))!.Content);
                Assert.Equal("Ядро недоступно",(await store.GetUploadAsync(savedId,default))!.Info.Error);
                await store.SetUploadResultAsync(savedId,new ParsedDocument{FileName=info.FileName,Title="Объект",Summary=[new SummaryItem{Name="Стол"}]},null,default);
                await store.SetUploadResultAsync(savedId,null,"Поздняя ошибка",default);
                var detail=await store.GetUploadAsync(savedId,default);
                Assert.True(detail!.Info.Parsed);Assert.Null(detail.Info.Error);Assert.Equal("Стол",detail.Document!.Summary[0].Name);
                var rows=await store.ListUploadsAsync("Тестовый план",0,100,default);
                Assert.Single(rows,r=>r.ProjectId==project);
            }
        }
        finally
        {
            await using var db=new NpgsqlConnection(connection);await db.OpenAsync();
            await using var cmd=new NpgsqlCommand("DELETE FROM spec_uploads WHERE project_id=$1",db);
            cmd.Parameters.AddWithValue(project);await cmd.ExecuteNonQueryAsync();
        }
    }
}
