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
            i => new InternetLookup { Status = "found", Query = i.Name, LookedUpAt = "2026-09-25", Offers = [offer], Price = 1250, Provider = "fake", Searches = 2, Params = i.SearchParams });
        return Task.FromResult(result);
    }

    public List<Supplier> Suppliers { get; } = [];
    public int AutocrawlPages { get; set; } = 300;
    public int MinShops { get; set; } = 3;

    public Task<SupplierIndexInfo> GetSuppliersAsync(CancellationToken ct) =>
        Task.FromResult(new SupplierIndexInfo
        {
            Suppliers = Suppliers.ToList(),
            Offers = Suppliers.Sum(s => s.Offers),
            UpdatedAt = Suppliers.Count > 0 ? "2026-09-25" : "",
            AutocrawlPages = AutocrawlPages,
            MinShops = MinShops,
            SearchEngine = "fake-search",
        });

    public Task<SupplierIndexInfo> UpdateSupplierSettingsAsync(SupplierSettings settings, CancellationToken ct)
    {
        AutocrawlPages = settings.AutocrawlPages;
        MinShops = settings.MinShops;
        return GetSuppliersAsync(ct);
    }

    public Task<Supplier> AddSupplierAsync(SupplierCreate supplier, CancellationToken ct)
    {
        var created = new Supplier { Id = $"s{Suppliers.Count + 1}", Name = supplier.Name, Site = supplier.Site, Kind = supplier.Site.Length > 0 ? "site" : "pricelist", MaxPages = supplier.MaxPages };
        Suppliers.Add(created);
        return Task.FromResult(created);
    }

    public Task RemoveSupplierAsync(string id, CancellationToken ct)
    {
        if (Suppliers.RemoveAll(s => s.Id == id) == 0) throw new NotFoundException("Поставщик не найден");
        return Task.CompletedTask;
    }

    public Task<Supplier> StartCrawlAsync(string id, CancellationToken ct)
    {
        var supplier = Find(id);
        if (supplier.Site.Length == 0) throw new ValidationFailedException("у поставщика не указан сайт — загрузите прайс-лист");
        return Task.FromResult(Replace(supplier with { Status = "running", Progress = "начинаем" }));
    }

    public Task<Supplier> StopCrawlAsync(string id, CancellationToken ct) => Task.FromResult(Replace(Find(id) with { Status = "done", Progress = "" }));

    public Task<Supplier> UploadSupplierPriceListAsync(string id, Stream xlsx, string fileName, string section, CancellationToken ct)
    {
        var supplier = Find(id);
        var sections = supplier.Sections.ToList();
        if (section.Length > 0 && !sections.Contains(section)) sections.Add(section);
        var source = section.Length > 0 ? $"прайс «{section}» {fileName}" : "прайс " + fileName;
        return Task.FromResult(Replace(supplier with { Offers = 2, Source = source, Status = "done", CollectedAt = "2026-09-25", Sections = sections }));
    }

    public Task<Supplier> UpdateSupplierAsync(string id, SupplierUpdate update, CancellationToken ct)
    {
        var supplier = Find(id);
        return Task.FromResult(Replace(supplier with
        {
            Name = update.Name ?? supplier.Name,
            Sections = update.Sections ?? supplier.Sections,
            MaxPages = update.MaxPages ?? supplier.MaxPages,
        }));
    }

    public List<IndexationRate> IndexationRates { get; } = [];

    public Task<IndexationInfo> GetIndexationAsync(CancellationToken ct) =>
        Task.FromResult(new IndexationInfo
        {
            History = new HistoryIndexation
            {
                Overall = new IndexationGroup { Group = "все группы", Rate = 3.5, Samples = 714 },
                Groups = [new IndexationGroup { Group = "Мебель", Rate = 1.0, Samples = 115, Pairs = [new IndexationPair { Years = "2024→2025", Rate = 1.0, Samples = 115 }] }],
                ComputedAt = "2026-09-28",
            },
            Rates = IndexationRates.ToList(),
        });

    public Task<IndexationInfo> SetIndexationAsync(IndexationRates rates, CancellationToken ct)
    {
        IndexationRates.Clear();
        IndexationRates.AddRange(rates.Rates.Select(r => r with { UpdatedAt = r.UpdatedAt.Length > 0 ? r.UpdatedAt : "2026-09-28" }));
        return GetIndexationAsync(ct);
    }

    public Task<IReadOnlyList<SupplierOffer>> SampleOffersAsync(string id, CancellationToken ct)
    {
        var supplier = Find(id);
        IReadOnlyList<SupplierOffer> offers = supplier.Offers == 0
            ? []
            : [new SupplierOffer { SupplierId = id, Supplier = supplier.Name, Name = "Стул детский", Price = 950, Sku = "ST-2", CollectedAt = "2026-09-25" }, new SupplierOffer { SupplierId = id, Supplier = supplier.Name, Name = "Стол трапециевидный", Price = 3100 }];
        return Task.FromResult(offers);
    }

    private Supplier Find(string id) => Suppliers.FirstOrDefault(s => s.Id == id) ?? throw new NotFoundException("Поставщик не найден");

    private Supplier Replace(Supplier supplier)
    {
        var index = Suppliers.FindIndex(s => s.Id == supplier.Id);
        Suppliers[index] = supplier;
        return supplier;
    }
}

public sealed class FakeEngine : IParsingEngine
{
    public Task<DrawingText> ExtractDrawingTextAsync(Stream pdf, string pages, CancellationToken ct)
    {
        if (Down) throw new ServiceUnavailableException("Ядро разбора недоступно.");
        return Task.FromResult(new DrawingText { Pages = [new DrawingPage { Number = 1,
            Lines = [new DrawingLine { Text = "2.10 = 26", X = 100, Y = 50 }] }] });
    }
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
