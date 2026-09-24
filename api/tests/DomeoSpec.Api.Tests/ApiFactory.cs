using DomeoSpec.Application.Common;
using DomeoSpec.Application.Parsing;
using DomeoSpec.Domain.Specifications;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace DomeoSpec.Api.Tests;

/// <summary>API целиком, но вместо Python-ядра — подставной порт: тесты не зависят от запущенного сервиса.</summary>
public sealed class ApiFactory : WebApplicationFactory<Program>
{
    public FakeEngine Engine { get; } = new();

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Testing");
        builder.UseSetting("Engine:BaseUrl", "http://engine.test");
        builder.ConfigureServices(services =>
        {
            services.RemoveAll<IParsingEngine>();
            services.AddSingleton<IParsingEngine>(Engine);
        });
    }
}

public sealed class FakeEngine : IParsingEngine
{
    public bool Down { get; set; }
    public ParsedDocument? LastExported { get; private set; }

    public Task<ParsedDocument> ParseAsync(Stream pdf, string fileName, CancellationToken ct)
    {
        if (Down) throw new ServiceUnavailableException("Ядро разбора недоступно.");
        return Task.FromResult(new ParsedDocument
        {
            FileName = fileName,
            DocCode = "ТЕСТ-ТХ",
            Pages = [new PageInfo { Number = 1, Kind = "spec", Rows = 1 }],
            Items = [new SpecItem { Id = 1, Page = 1, Pos = "2.10", PosKey = "2.10", Name = "Стул", Description = "Стул детский", Unit = "шт.", Qty = 26, QtyRaw = "26" }],
            Summary = [new SummaryItem { Pos = "2.10", PosKey = "2.10", Name = "Стул", Description = "Стул детский", Unit = "шт.", Qty = 26, ItemIds = [1] }],
        });
    }

    public Task<ExportedFile> ExportAsync(ParsedDocument document, CancellationToken ct)
    {
        if (Down) throw new ServiceUnavailableException("Ядро разбора недоступно.");
        LastExported = document;
        return Task.FromResult(new ExportedFile([1, 2, 3], "тест.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"));
    }

    public Task<EngineHealth> GetHealthAsync(CancellationToken ct) =>
        Task.FromResult(Down ? new EngineHealth(false, null) : new EngineHealth(true, "tesseract"));
}
