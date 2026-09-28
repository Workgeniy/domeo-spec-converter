using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;

namespace DomeoSpec.Api.Tests;

public sealed class IndexationApiTests : IClassFixture<ApiFactory>
{
    private readonly ApiFactory _factory;
    private readonly HttpClient _client;

    public IndexationApiTests(ApiFactory factory)
    {
        _factory = factory;
        _factory.Pricing.IndexationRates.Clear();
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task Get_returns_history_and_rates()
    {
        var body = await _client.GetFromJsonAsync<JsonNode>("/api/specifications/indexation");
        var data = body!["data"]!;
        Assert.Equal(3.5, data["history"]!["overall"]!["rate"]!.GetValue<double>());
        Assert.Equal("Мебель", data["history"]!["groups"]![0]!["group"]!.GetValue<string>());
        Assert.Equal("2024→2025", data["history"]!["groups"]![0]!["pairs"]![0]!["years"]!.GetValue<string>());
        Assert.Empty(data["rates"]!.AsArray());
    }

    [Fact]
    public async Task Put_validates_and_stores_rates()
    {
        var ok = await _client.PutAsJsonAsync("/api/specifications/indexation", new
        {
            rates = new[]
            {
                new { section = " Мебель ", rate = 5.0, source = "history", note = "по истории" },
                new { section = "", rate = 3.5, source = "official", note = "ИПЦ" },
            },
        });
        Assert.Equal(HttpStatusCode.OK, ok.StatusCode);
        var rates = (await ok.Content.ReadFromJsonAsync<JsonNode>())!["data"]!["rates"]!.AsArray();
        Assert.Equal("Мебель", rates[0]!["section"]!.GetValue<string>());
        Assert.Equal("", rates[1]!["section"]!.GetValue<string>());
        Assert.Equal("2026-09-28", rates[0]!["updated_at"]!.GetValue<string>());

        var tooHigh = await _client.PutAsJsonAsync("/api/specifications/indexation", new { rates = new[] { new { section = "Мебель", rate = 500.0, source = "manual" } } });
        Assert.Equal(HttpStatusCode.BadRequest, tooHigh.StatusCode);
        var badSource = await _client.PutAsJsonAsync("/api/specifications/indexation", new { rates = new[] { new { section = "Мебель", rate = 5.0, source = "guess" } } });
        Assert.Equal(HttpStatusCode.BadRequest, badSource.StatusCode);
        var duplicate = await _client.PutAsJsonAsync("/api/specifications/indexation", new { rates = new[] { new { section = "Мебель", rate = 5.0, source = "manual" }, new { section = "мебель", rate = 6.0, source = "manual" } } });
        Assert.Equal(HttpStatusCode.BadRequest, duplicate.StatusCode);
    }
}
