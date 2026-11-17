using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;

namespace DomeoSpec.Api.Tests;

/// <summary>Мост браузерного расширения: ping, обмен «спека ↔ расширение» и очередь найденных цен.</summary>
public sealed class ExtensionBridgeApiTests : IClassFixture<ApiFactory>
{
    private readonly HttpClient _client;

    public ExtensionBridgeApiTests(ApiFactory factory) => _client = factory.CreateClient();

    [Fact]
    public async Task Ping_reports_app()
    {
        var body = await _client.GetFromJsonAsync<JsonNode>("/ext/ping");
        Assert.True(body!["success"]!.GetValue<bool>());
        Assert.Equal("domeo", body["data"]!["app"]!.GetValue<string>());
    }

    [Fact]
    public async Task Spec_round_trips()
    {
        var set = await _client.PostAsJsonAsync("/ext/spec/current", new[]
        {
            new { id = "1", name = "Смеситель для кухни", qty = 2.5 }, // дробное кол-во (м²/пог.м) должно проходить
            new { id = "2", name = "Мойка нержавеющая", qty = 1.0 },
        });
        Assert.Equal(HttpStatusCode.OK, set.StatusCode);

        var body = await _client.GetFromJsonAsync<JsonNode>("/ext/spec/current");
        var items = body!["data"]!["items"]!.AsArray();
        Assert.Equal(2, items.Count);
        Assert.Equal("Смеситель для кухни", items[0]!["name"]!.GetValue<string>());
        Assert.Equal(2.5, items[0]!["qty"]!.GetValue<double>());
    }

    [Fact]
    public async Task Price_is_queued_and_drained_once()
    {
        await _client.GetFromJsonAsync<JsonNode>("/ext/prices"); // очистить остаток от других тестов

        var post = await _client.PostAsJsonAsync("/ext/price", new
        {
            spec_item_id = "2",
            source = "wildberries",
            name = "Смеситель для кухни Palidore",
            price = 2167,
            old_price = 6881,
            url = "https://www.wildberries.ru/catalog/373658712/detail.aspx",
            seller = "Palidore",
            rating = 4.8,
        });
        Assert.Equal(HttpStatusCode.OK, post.StatusCode);

        var drained = (await _client.GetFromJsonAsync<JsonNode>("/ext/prices"))!["data"]!.AsArray();
        Assert.Single(drained);
        Assert.Equal(2167, drained[0]!["price"]!.GetValue<int>());
        Assert.Equal("2", drained[0]!["spec_item_id"]!.GetValue<string>());
        Assert.Equal("Palidore", drained[0]!["seller"]!.GetValue<string>());

        var again = (await _client.GetFromJsonAsync<JsonNode>("/ext/prices"))!["data"]!.AsArray();
        Assert.Empty(again); // очередь очищается при заборе
    }

    [Fact]
    public async Task Price_without_name_is_validation_error()
    {
        var post = await _client.PostAsJsonAsync("/ext/price", new { spec_item_id = "1", source = "wildberries", price = 100 });
        Assert.Equal(HttpStatusCode.BadRequest, post.StatusCode);
        var problem = await post.Content.ReadFromJsonAsync<JsonNode>();
        Assert.Equal("validation_failed", problem!["code"]!.GetValue<string>());
    }
}
