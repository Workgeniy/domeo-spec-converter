using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using DomeoSpec.Application.Parsing;
using DomeoSpec.Domain.Specifications;

namespace DomeoSpec.Api.Tests;

public sealed class DrawingTests : IClassFixture<ApiFactory>
{
    private readonly HttpClient client;
    public DrawingTests(ApiFactory factory) { factory.Engine.Down = false; client = factory.CreateClient(); }

    private static MultipartFormDataContent Form(string pages = "1") => new()
    {
        { new ByteArrayContent([1, 2, 3]), "file", "plan.pdf" },
        { new StringContent(pages), "pages" },
        { new StringContent("[{\"pos\":\"2.10\",\"name\":\"Стул\",\"qty\":26,\"unit\":\"шт.\"}]"), "items" },
    };

    [Fact]
    public async Task Endpoint_compares_against_fake_engine()
    {
        using var form = Form();
        var response = await client.PostAsync("/api/specifications/check-drawing", form);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var json = await response.Content.ReadFromJsonAsync<JsonNode>();
        Assert.Equal("match", json!["data"]!["rows"]![0]!["status"]!.GetValue<string>());
        Assert.Equal(26, json["data"]!["rows"]![0]!["found"]!.GetValue<int>());
        Assert.Equal(100, json["data"]!["rows"]![0]!["hits"]![0]!["x"]!.GetValue<double>());
    }

    [Theory]
    [InlineData("abc")]
    [InlineData("0")]
    [InlineData("1-3")]
    public async Task Endpoint_rejects_bad_page_selection(string pages)
    {
        using var form = Form(pages);
        Assert.Equal(HttpStatusCode.BadRequest, (await client.PostAsync("/api/specifications/check-drawing", form)).StatusCode);
    }

    [Fact]
    public void Compare_handles_counts_duplicates_nonpiece_units_and_dimensions()
    {
        var drawing = new DrawingText { Pages = [new DrawingPage { Number = 3, Lines =
            [new() { Text = "1,1" }, new() { Text = "1.1 = 6" }, new() { Text = "2" }, new() { Text = "3" },
             new() { Text = "4" }, new() { Text = "999" }, new() { Text = "1000x600" }] }] };
        var result = CheckDrawingHandler.Compare(drawing,
            [new() { Pos = "1.1", Qty = 7, Unit = "шт." }, new() { Pos = "2", Qty = 2, Unit = "шт." },
             new() { Pos = "3", Qty = 1, Unit = "шт." }, new() { Pos = "3", Qty = 1, Unit = "шт." },
             new() { Pos = "4", Qty = 2, Unit = "м²" }, new() { Pos = "5", Qty = 1, Unit = "шт." }]);
        Assert.Equal(["match", "difference", "ambiguous", "quantity_not_comparable", "not_found"], result.Rows.Select(r => r.Status));
        Assert.Equal(7, result.Rows[0].Found);
        Assert.Single(result.UnknownLabels);
        Assert.StartsWith("999", result.UnknownLabels[0]);
    }

    [Fact]
    public void Skipped_scan_is_not_reported_as_missing_equipment()
    {
        var result = CheckDrawingHandler.Compare(new DrawingText { Pages = [new() { Number = 1, SkippedReason = "Скан" }] },
            [new() { Pos = "1", Qty = 3, Unit = "шт." }]);
        Assert.Equal("not_checked", result.Rows[0].Status);
        Assert.Contains(result.Warnings, w => w.Contains("Скан"));
    }
}
