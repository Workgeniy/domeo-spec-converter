using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;

namespace DomeoSpec.Api.Tests;

public sealed class InternetApiTests : IClassFixture<ApiFactory>
{
    private readonly ApiFactory _factory;
    private readonly HttpClient _client;

    public InternetApiTests(ApiFactory factory)
    {
        _factory = factory;
        _factory.Pricing.InternetConfigured = true;
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task Get_reports_search_state()
    {
        var body = await _client.GetFromJsonAsync<JsonNode>("/api/specifications/internet");
        Assert.True(body!["success"]!.GetValue<bool>());
        Assert.True(body["data"]!["configured"]!.GetValue<bool>());
        Assert.Equal("claude-opus-5", body["data"]!["model"]!.GetValue<string>());
        Assert.Equal(7, body["data"]!["ttl_days"]!.GetValue<int>());
    }

    [Fact]
    public async Task Lookup_returns_offers_per_item()
    {
        var response = await _client.PostAsJsonAsync("/api/specifications/internet/lookup", new
        {
            items = new[] { new { id = "d1:0", name = "Стул детский", description = "регулируемый", unit = "шт." } },
            refresh = true,
        });
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var lookups = (await response.Content.ReadFromJsonAsync<JsonNode>())!["data"]!["lookups"]!;
        Assert.Equal("found", lookups["d1:0"]!["status"]!.GetValue<string>());
        Assert.Equal(1250, lookups["d1:0"]!["price"]!.GetValue<double>());
        Assert.Equal("https://shop.example/1", lookups["d1:0"]!["offers"]![0]!["url"]!.GetValue<string>());
        Assert.Equal("2026-09-25", lookups["d1:0"]!["looked_up_at"]!.GetValue<string>());
        Assert.True(_factory.Pricing.LastRefresh);
        Assert.Equal("шт.", _factory.Pricing.LastLookedUp![0].Unit);
    }

    [Fact]
    public async Task Lookup_passes_operator_params_to_the_engine()
    {
        var response = await _client.PostAsJsonAsync("/api/specifications/internet/lookup", new
        {
            items = new object[]
            {
                new { id = "d1:0", name = "Стол обеденный", search_params = new[] { new { name = "Материал ножек", value = "металл" } } },
                new { id = "d1:1", name = "Стул", type_mark = "по типу Polair CM107-S" },
            },
        });
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var sent = _factory.Pricing.LastLookedUp!;
        Assert.Equal("Материал ножек", Assert.Single(sent[0].SearchParams).Name);
        Assert.Equal("металл", sent[0].SearchParams[0].Value);
        Assert.Empty(sent[1].SearchParams); // не передали — пустой список
        Assert.Equal("по типу Polair CM107-S", sent[1].TypeMark);
        Assert.Equal("", sent[0].TypeMark);
        var lookups = (await response.Content.ReadFromJsonAsync<JsonNode>())!["data"]!["lookups"]!;
        Assert.Equal("металл", lookups["d1:0"]!["params"]![0]!["value"]!.GetValue<string>());

        var tooMany = await _client.PostAsJsonAsync("/api/specifications/internet/lookup", new
        {
            items = new[] { new { id = "a", name = "Стол", search_params = Enumerable.Range(0, 11).Select(i => new { name = $"п{i}", value = "x" }).ToArray() } },
        });
        Assert.Equal(HttpStatusCode.BadRequest, tooMany.StatusCode);
        var tooLong = await _client.PostAsJsonAsync("/api/specifications/internet/lookup", new
        {
            items = new[] { new { id = "a", name = "Стол", search_params = new[] { new { name = "Материал", value = new string('м', 121) } } } },
        });
        Assert.Equal(HttpStatusCode.BadRequest, tooLong.StatusCode);
    }

    [Fact]
    public async Task Lookup_validates_input()
    {
        var empty = await _client.PostAsJsonAsync("/api/specifications/internet/lookup", new { items = Array.Empty<object>() });
        Assert.Equal(HttpStatusCode.BadRequest, empty.StatusCode);
        var problem = await empty.Content.ReadFromJsonAsync<JsonNode>();
        Assert.Equal("validation_failed", problem!["code"]!.GetValue<string>());

        var tooMany = await _client.PostAsJsonAsync("/api/specifications/internet/lookup", new
        {
            items = Enumerable.Range(0, 51).Select(i => new { id = i.ToString(), name = $"Позиция {i}" }).ToArray(),
        });
        Assert.Equal(HttpStatusCode.BadRequest, tooMany.StatusCode);
    }

    [Fact]
    public async Task Lookup_without_key_is_a_validation_error()
    {
        _factory.Pricing.InternetConfigured = false;
        try
        {
            var response = await _client.PostAsJsonAsync("/api/specifications/internet/lookup", new { items = new[] { new { id = "a", name = "Стул" } } });
            Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
            var state = await _client.GetFromJsonAsync<JsonNode>("/api/specifications/internet");
            Assert.False(state!["data"]!["configured"]!.GetValue<bool>());
        }
        finally
        {
            _factory.Pricing.InternetConfigured = true;
        }
    }
}
