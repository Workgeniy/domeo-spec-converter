using DomeoSpec.Infrastructure.Quotations;
using DomeoSpec.Domain.Quotations;
using Microsoft.Extensions.Configuration;
using Npgsql;
namespace DomeoSpec.Api.Tests;
public sealed class PostgresFactAttribute : FactAttribute
{
    public PostgresFactAttribute() { if(string.IsNullOrEmpty(Environment.GetEnvironmentVariable("TEST_QUOTATIONS_CONNECTION"))) Skip="Нужна отдельная тестовая PostgreSQL: TEST_QUOTATIONS_CONNECTION"; }
}
public sealed class PostgresQuotationsTests
{
    [PostgresFact]
    public async Task Persists_across_instances_and_concurrent_retries_and_pages_without_payload()
    {
        var connection=Environment.GetEnvironmentVariable("TEST_QUOTATIONS_CONNECTION")!;
        var config=new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string,string?> { ["ConnectionStrings:Quotations"]=connection }).Build();
        var req=QuotationsApiTests.Request();
        var info=new QuotationInfo(req.Id,req.ProjectId,null,DateTime.UtcNow,"Тест ' SQL", "42",1,20,"Моя форма","test.xlsx");
        var q=new StoredQuotation(info,req.Snapshot,"hash",[5,6,7],"application/xlsx");
        try
        {
            using(var store=new PostgresQuotationStore(config))
            {
                await Task.WhenAll(Enumerable.Range(0,5).Select(_=>store.InsertAsync(q,default)));
                Assert.Single(await store.ListAsync("' SQL",req.ProjectId,0,30,default));
            }
            using(var reopened=new PostgresQuotationStore(config))
            {
                var detail=await reopened.GetAsync(req.Id,default);
                Assert.Equal(20,detail!.Snapshot.Kp.MarginPercent);
                Assert.True(detail.Snapshot.Documents[0].Doc.Summary[1].Excluded);
                Assert.Equal(10,detail.Snapshot.Indexation.Rates["Мебель IKEA"]);
                Assert.Equal(new byte[] {5,6,7},(await reopened.GetFileAsync(req.Id,default))!.Content);
                Assert.Equal("hash",await reopened.GetRequestHashAsync(req.Id,default));
                Assert.Empty(await reopened.ListAsync("",req.ProjectId,1,30,default));
                Assert.Null(await reopened.GetAsync(Guid.NewGuid(),default));
            }
        }
        finally
        {
            await using var db=new NpgsqlConnection(connection);await db.OpenAsync();
            await using var cmd=new NpgsqlCommand("DELETE FROM spec_quotations WHERE project_id=$1",db);
            cmd.Parameters.AddWithValue(req.ProjectId);await cmd.ExecuteNonQueryAsync();
        }
    }
}
