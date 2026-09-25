using DomeoSpec.Application.Common;
using DomeoSpec.Application.Parsing;
using DomeoSpec.Application.Pricing;
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
    public FakePricing Pricing { get; } = new();

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Testing");
        builder.UseSetting("Engine:BaseUrl", "http://engine.test");
        builder.ConfigureServices(services =>
        {
            services.RemoveAll<IParsingEngine>();
            services.AddSingleton<IParsingEngine>(Engine);
            services.RemoveAll<IPricingEngine>();
            services.AddSingleton<IPricingEngine>(Pricing);
        });
    }
}

public sealed class FakePricing : IPricingEngine
{
    public PriceListInfo? Info { get; set; }
    public IReadOnlyList<MatchRequestItem>? LastMatched { get; private set; }

    public Task<PriceListInfo> UploadPriceListAsync(Stream xlsx, string fileName, CancellationToken ct)
    {
        Info = new PriceListInfo { Source = fileName, Entries = 3, RowsTotal = 8, PeriodFrom = "2023-02-10", PeriodTo = "2025-04-01" };
        return Task.FromResult(Info);
    }

    public Task<PriceListInfo?> GetPriceListAsync(CancellationToken ct) => Task.FromResult(Info);

    public Task<IReadOnlyDictionary<string, HistoryPrice>> MatchAsync(IReadOnlyList<MatchRequestItem> items, CancellationToken ct)
    {
        if (Info is null) throw new ValidationFailedException("Прайс закупки ещё не загружен.");
        LastMatched = items;
        var best = new HistoryCandidate { Key = "стул детский", Name = "Стул детский регулируемый", Score = 1.0, PriceMin = 950, PriceMax = 2600, PriceLast = 2600, Purchases = 19 };
        IReadOnlyDictionary<string, HistoryPrice> result = items.ToDictionary(
            i => i.Id,
            i => i.Name.Contains("Стул") ? new HistoryPrice { Kind = "exact", Best = best, Candidates = [best] } : new HistoryPrice { Kind = "none" });
        return Task.FromResult(result);
    }

    public bool InternetConfigured { get; set; } = true;
    public IReadOnlyList<MatchRequestItem>? LastLookedUp { get; private set; }
    public bool LastRefresh { get; private set; }

    public Task<InternetSearchInfo> GetInternetSearchAsync(CancellationToken ct) =>
        Task.FromResult(new InternetSearchInfo
        {
            Configured = InternetConfigured,
            Provider = InternetConfigured ? "claude-web-search" : "",
            Model = InternetConfigured ? "claude-opus-5" : "",
            Cached = 2,
        });

    public Task<IReadOnlyDictionary<string, InternetLookup>> LookupInternetAsync(IReadOnlyList<MatchRequestItem> items, bool refresh, CancellationToken ct)
    {
        if (!InternetConfigured) throw new ValidationFailedException("Поиск цен в интернете не настроен.");
        LastLookedUp = items;
        LastRefresh = refresh;
        var offer = new InternetOffer { Title = "Стул детский регулируемый", Url = "https://shop.example/1", Shop = "Магазин", Price = 1250 };
        IReadOnlyDictionary<string, InternetLookup> result = items.ToDictionary(
            i => i.Id,
            i => new InternetLookup { Status = "found", Query = i.Name, LookedUpAt = "2026-09-25", Offers = [offer], Price = 1250, Provider = "fake", Searches = 2 });
        return Task.FromResult(result);
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
