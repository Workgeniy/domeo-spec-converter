using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json.Nodes;

namespace DomeoSpec.Api.Tests;

public sealed class PriceListApiTests : IClassFixture<ApiFactory>
{
    private readonly ApiFactory _factory;
    private readonly HttpClient _client;

    public PriceListApiTests(ApiFactory factory)
    {
        _factory = factory;
        _factory.Pricing.Info = null;
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task Get_without_price_list_returns_null_data()
    {
        var body = await _client.GetFromJsonAsync<JsonNode>("/api/specifications/pricelist");
        Assert.True(body!["success"]!.GetValue<bool>());
        Assert.Null(body["data"]);
    }

    [Fact]
    public async Task Upload_then_get_and_match()
    {
        using var form = new MultipartFormDataContent();
        var file = new ByteArrayContent("PK\u0003\u0004fake"u8.ToArray());
        file.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
        form.Add(file, "file", "История закупок.xlsx");
        var upload = await _client.PostAsync("/api/specifications/pricelist", form);
        Assert.Equal(HttpStatusCode.OK, upload.StatusCode);
        var info = (await upload.Content.ReadFromJsonAsync<JsonNode>())!["data"]!;
        Assert.Equal("История закупок.xlsx", info["source"]!.GetValue<string>());
        Assert.Equal(3, info["entries"]!.GetValue<int>());

        var get = await _client.GetFromJsonAsync<JsonNode>("/api/specifications/pricelist");
        Assert.Equal("2023-02-10", get!["data"]!["period_from"]!.GetValue<string>());

        var match = await _client.PostAsJsonAsync("/api/specifications/pricelist/match", new
        {
            items = new[] { new { id = "d1:0", name = "Стул детский", description = "" }, new { id = "d1:1", name = "Проектор", description = "" } },
        });
        Assert.Equal(HttpStatusCode.OK, match.StatusCode);
        var matches = (await match.Content.ReadFromJsonAsync<JsonNode>())!["data"]!["matches"]!;
        Assert.Equal("exact", matches["d1:0"]!["kind"]!.GetValue<string>());
        Assert.Equal(950, matches["d1:0"]!["best"]!["price_min"]!.GetValue<double>());
        Assert.Equal("none", matches["d1:1"]!["kind"]!.GetValue<string>());
        Assert.Equal(2, _factory.Pricing.LastMatched!.Count);
    }

    [Fact]
    public async Task Upload_rejects_non_xlsx()
    {
        using var form = new MultipartFormDataContent();
        form.Add(new ByteArrayContent([1, 2, 3]), "file", "history.csv");
        var r = await _client.PostAsync("/api/specifications/pricelist", form);
        Assert.Equal(HttpStatusCode.BadRequest, r.StatusCode);
        Assert.Equal("validation_failed", (await r.Content.ReadFromJsonAsync<JsonNode>())!["code"]!.GetValue<string>());
    }

    [Fact]
    public async Task Match_without_price_list_is_400()
    {
        var r = await _client.PostAsJsonAsync("/api/specifications/pricelist/match", new { items = new[] { new { id = "1", name = "Стул" } } });
        Assert.Equal(HttpStatusCode.BadRequest, r.StatusCode);
        Assert.Contains("не загружен", (await r.Content.ReadFromJsonAsync<JsonNode>())!["detail"]!.GetValue<string>());
    }

    [Fact]
    public async Task Match_with_empty_items_is_400()
    {
        _factory.Pricing.Info = new Domain.Specifications.PriceListInfo { Source = "x.xlsx" };
        var r = await _client.PostAsJsonAsync("/api/specifications/pricelist/match", new { items = Array.Empty<object>() });
        Assert.Equal(HttpStatusCode.BadRequest, r.StatusCode);
    }
}
