using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json.Nodes;

namespace DomeoSpec.Api.Tests;

public sealed class SuppliersApiTests : IClassFixture<ApiFactory>
{
    private readonly ApiFactory _factory;
    private readonly HttpClient _client;

    public SuppliersApiTests(ApiFactory factory)
    {
        _factory = factory;
        _factory.Pricing.Suppliers.Clear();
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task Add_validates_name_and_site()
    {
        var noName = await _client.PostAsJsonAsync("/api/specifications/suppliers", new { name = "  ", site = "" });
        Assert.Equal(HttpStatusCode.BadRequest, noName.StatusCode);
        Assert.Equal("validation_failed", (await noName.Content.ReadFromJsonAsync<JsonNode>())!["code"]!.GetValue<string>());

        var badSite = await _client.PostAsJsonAsync("/api/specifications/suppliers", new { name = "Кворус", site = "просто текст" });
        Assert.Equal(HttpStatusCode.BadRequest, badSite.StatusCode);

        var ok = await _client.PostAsJsonAsync("/api/specifications/suppliers", new { name = " Кворус ", site = "kvorus.ru", max_pages = 10 });
        Assert.Equal(HttpStatusCode.OK, ok.StatusCode);
        var created = (await ok.Content.ReadFromJsonAsync<JsonNode>())!["data"]!;
        Assert.Equal("Кворус", created["name"]!.GetValue<string>());
        Assert.Equal(50, created["max_pages"]!.GetValue<int>());  // нижняя граница
        Assert.Equal("site", created["kind"]!.GetValue<string>());
    }

    [Fact]
    public async Task Crawl_stop_pricelist_sample_and_delete()
    {
        var add = await _client.PostAsJsonAsync("/api/specifications/suppliers", new { name = "Прайсовый", site = "" });
        var id = (await add.Content.ReadFromJsonAsync<JsonNode>())!["data"]!["id"]!.GetValue<string>();

        var crawl = await _client.PostAsync($"/api/specifications/suppliers/{id}/crawl", null);
        Assert.Equal(HttpStatusCode.BadRequest, crawl.StatusCode);  // сайта нет

        using var form = new MultipartFormDataContent();
        var file = new ByteArrayContent("PK\u0003\u0004fake"u8.ToArray());
        file.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
        form.Add(file, "file", "прайс сентябрь.xlsx");
        var upload = await _client.PostAsync($"/api/specifications/suppliers/{id}/pricelist", form);
        Assert.Equal(HttpStatusCode.OK, upload.StatusCode);
        var uploaded = (await upload.Content.ReadFromJsonAsync<JsonNode>())!["data"]!;
        Assert.Equal(2, uploaded["offers"]!.GetValue<int>());
        Assert.Equal("прайс прайс сентябрь.xlsx", uploaded["source"]!.GetValue<string>());

        var list = await _client.GetFromJsonAsync<JsonNode>("/api/specifications/suppliers");
        Assert.Equal(2, list!["data"]!["offers"]!.GetValue<int>());
        Assert.Equal("done", list["data"]!["suppliers"]![0]!["status"]!.GetValue<string>());

        var sample = await _client.GetFromJsonAsync<JsonNode>($"/api/specifications/suppliers/{id}/sample");
        Assert.Equal(950, sample!["data"]!["offers"]![0]!["price"]!.GetValue<double>());

        var delete = await _client.DeleteAsync($"/api/specifications/suppliers/{id}");
        Assert.Equal(HttpStatusCode.NoContent, delete.StatusCode);
        var missing = await _client.PostAsync($"/api/specifications/suppliers/{id}/crawl", null);
        Assert.Equal(HttpStatusCode.NotFound, missing.StatusCode);
        Assert.Equal("not_found", (await missing.Content.ReadFromJsonAsync<JsonNode>())!["code"]!.GetValue<string>());
    }

    [Fact]
    public async Task Crawl_runs_in_background_and_can_be_stopped()
    {
        var add = await _client.PostAsJsonAsync("/api/specifications/suppliers", new { name = "Сайт", site = "https://shop.test" });
        var id = (await add.Content.ReadFromJsonAsync<JsonNode>())!["data"]!["id"]!.GetValue<string>();
        var crawl = await _client.PostAsync($"/api/specifications/suppliers/{id}/crawl", null);
        Assert.Equal(HttpStatusCode.OK, crawl.StatusCode);
        Assert.Equal("running", (await crawl.Content.ReadFromJsonAsync<JsonNode>())!["data"]!["status"]!.GetValue<string>());
        var stop = await _client.PostAsync($"/api/specifications/suppliers/{id}/stop", null);
        Assert.Equal("done", (await stop.Content.ReadFromJsonAsync<JsonNode>())!["data"]!["status"]!.GetValue<string>());
        var upload = await _client.PostAsync($"/api/specifications/suppliers/{id}/pricelist", new MultipartFormDataContent());
        Assert.Equal(HttpStatusCode.BadRequest, upload.StatusCode);  // файла нет
    }
}
