using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace DomeoSpec.Api.Tests;

public sealed class SpecificationsApiTests : IClassFixture<ApiFactory>
{
    private readonly ApiFactory _factory;
    private readonly HttpClient _client;

    public SpecificationsApiTests(ApiFactory factory)
    {
        _factory = factory;
        _factory.Engine.Down = false;
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task Health_reports_engine_state()
    {
        var body = await _client.GetFromJsonAsync<JsonNode>("/api/health");
        Assert.True(body!["success"]!.GetValue<bool>());
        Assert.Equal("ok", body["data"]!["status"]!.GetValue<string>());
        Assert.True(body["data"]!["engine"]!["available"]!.GetValue<bool>());
        Assert.Equal("tesseract", body["data"]!["engine"]!["ocr"]!.GetValue<string>());
    }

    [Fact]
    public async Task Parse_returns_document_in_envelope_with_snake_case()
    {
        using var form = PdfForm("том.pdf");
        var response = await _client.PostAsync("/api/specifications/parse", form);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var body = await response.Content.ReadFromJsonAsync<JsonNode>();
        Assert.True(body!["success"]!.GetValue<bool>());
        var data = body["data"]!;
        Assert.Equal("ТЕСТ-ТХ", data["doc_code"]!.GetValue<string>());
        Assert.Equal("2.10", data["items"]![0]!["pos_key"]!.GetValue<string>());
        Assert.Equal(26, data["summary"]![0]!["qty"]!.GetValue<double>());
    }

    [Fact]
    public async Task Parse_rejects_non_pdf_with_problem_details()
    {
        using var form = PdfForm("заметки.txt");
        var response = await _client.PostAsync("/api/specifications/parse", form);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        var problem = await response.Content.ReadFromJsonAsync<JsonNode>();
        Assert.Equal("validation_failed", problem!["code"]!.GetValue<string>());
        Assert.Contains("PDF", problem["detail"]!.GetValue<string>());
    }

    [Fact]
    public async Task Parse_without_file_is_400()
    {
        using var form = new MultipartFormDataContent { { new StringContent("x"), "other" } };
        var response = await _client.PostAsync("/api/specifications/parse", form);
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Export_roundtrips_document_and_returns_xlsx()
    {
        using var form = PdfForm("том.pdf");
        var parsed = await (await _client.PostAsync("/api/specifications/parse", form)).Content.ReadFromJsonAsync<JsonNode>();

        var response = await _client.PostAsJsonAsync("/api/specifications/export", parsed!["data"]);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", response.Content.Headers.ContentType!.MediaType);
        Assert.Contains("xlsx", response.Content.Headers.ContentDisposition!.ToString());
        Assert.Equal([1, 2, 3], await response.Content.ReadAsByteArrayAsync());
        // Документ дошёл до ядра в том же виде: snake_case JSON фронта → доменная модель.
        Assert.Equal("2.10", _factory.Engine.LastExported!.Summary[0].PosKey);
        Assert.Equal(26, _factory.Engine.LastExported.Items[0].Qty);
    }

    [Fact]
    public async Task Export_of_empty_document_is_400()
    {
        var response = await _client.PostAsJsonAsync("/api/specifications/export", new { file_name = "x.pdf" });
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Engine_down_is_503_with_retry_after()
    {
        _factory.Engine.Down = true;
        try
        {
            using var form = PdfForm("том.pdf");
            var response = await _client.PostAsync("/api/specifications/parse", form);

            Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
            Assert.Equal("5", response.Headers.RetryAfter!.ToString());
            var problem = await response.Content.ReadFromJsonAsync<JsonNode>();
            Assert.Equal("service_unavailable", problem!["code"]!.GetValue<string>());

            var health = await _client.GetFromJsonAsync<JsonNode>("/api/health");
            Assert.False(health!["data"]!["engine"]!["available"]!.GetValue<bool>());
        }
        finally
        {
            _factory.Engine.Down = false;
        }
    }

    private static MultipartFormDataContent PdfForm(string fileName)
    {
        var file = new ByteArrayContent("%PDF-1.4 fake"u8.ToArray());
        file.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
        return new MultipartFormDataContent { { file, "file", fileName } };
    }
}
