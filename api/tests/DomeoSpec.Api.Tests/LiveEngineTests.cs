using DomeoSpec.Infrastructure.Engine;

namespace DomeoSpec.Api.Tests;

/// <summary>
/// Сквозная проверка клиента против настоящего Python-ядра. Выполняется только если ядро
/// поднято на http://localhost:8000 и есть файл-образец; иначе тест пропускается.
/// </summary>
public sealed class LiveEngineTests
{
    private static readonly string SamplePath = Path.GetFullPath(Path.Combine(
        AppContext.BaseDirectory, "..", "..", "..", "..", "..", "..", "core", "tests", "samples", "ДОО350-ДОН-ПИР-П-ТХ2.pdf"));

    [Fact]
    public async Task Parse_and_export_against_running_engine()
    {
        using var http = new HttpClient { BaseAddress = new Uri("http://localhost:8000"), Timeout = TimeSpan.FromMinutes(2) };
        var client = new PythonEngineClient(http);
        var health = await client.GetHealthAsync(CancellationToken.None);
        if (!health.Available || !File.Exists(SamplePath))
            return; // ядро не запущено или нет образца — нечего проверять

        await using var pdf = File.OpenRead(SamplePath);
        var doc = await client.ParseAsync(pdf, Path.GetFileName(SamplePath), CancellationToken.None);
        Assert.Equal("ДОО350-ДОН-ПИР-П-ТХ2", doc.DocCode);
        Assert.Equal(139, doc.Items.Count);
        Assert.Equal(75, doc.Summary.Count);
        Assert.Equal("7.197", doc.Items[0].Pos);

        var file = await client.ExportAsync(doc, CancellationToken.None);
        Assert.EndsWith(".xlsx", file.FileName);
        Assert.True(file.Content.Length > 10_000);
    }
}
