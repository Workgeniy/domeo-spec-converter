using DomeoSpec.Application.Parsing;
using DomeoSpec.Application.Pricing;
using DomeoSpec.Application.Quotations;
using DomeoSpec.Application.Uploads;
using DomeoSpec.Infrastructure.Engine;
using DomeoSpec.Infrastructure.Quotations;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace DomeoSpec.Infrastructure;

public static class DependencyInjection
{
    /// <summary>
    /// Реализации портов. Адрес ядра проверяется здесь, на старте: относительный или пустой адрес —
    /// падение с внятным сообщением, а не тихие 503 на каждый запрос.
    /// </summary>
    public static IServiceCollection AddInfrastructure(this IServiceCollection services, IConfiguration configuration)
    {
        var options = configuration.GetSection(EngineOptions.Section).Get<EngineOptions>() ?? new EngineOptions();
        if (!Uri.TryCreate(options.BaseUrl, UriKind.Absolute, out var baseUri) || !baseUri.Scheme.StartsWith("http"))
        {
            throw new InvalidOperationException(
                $"{EngineOptions.Section}:BaseUrl должен быть абсолютным http(s)-адресом ядра разбора, получено «{options.BaseUrl}».");
        }

        services.AddHttpClient<IParsingEngine, PythonEngineClient>(client =>
        {
            client.BaseAddress = baseUri;
            client.Timeout = TimeSpan.FromSeconds(options.TimeoutSeconds);
        });
        services.AddHttpClient<IPricingEngine, PythonPricingClient>(client =>
        {
            client.BaseAddress = baseUri;
            client.Timeout = TimeSpan.FromSeconds(options.TimeoutSeconds);
        });
        // Хранилище истории КП / объектов / загрузок. Строка вида «Data Source=…» (без Host=) —
        // встроенный SQLite (автономный десктоп, без отдельного процесса БД); иначе PostgreSQL
        // (сервер/сеть). Пустая строка остаётся на PostgreSQL-варианте: он даёт внятную «БД не настроена».
        var quotations = configuration.GetConnectionString("Quotations");
        var useSqlite = !string.IsNullOrWhiteSpace(quotations) && !quotations.Contains("Host=", StringComparison.OrdinalIgnoreCase);
        if (useSqlite)
        {
            services.AddSingleton<SqliteQuotationStore>();
            services.AddSingleton<IQuotationStore>(s => s.GetRequiredService<SqliteQuotationStore>());
            services.AddSingleton<IProjectStore>(s => s.GetRequiredService<SqliteQuotationStore>());
            services.AddSingleton<IUploadStore>(s => s.GetRequiredService<SqliteQuotationStore>());
        }
        else
        {
            services.AddSingleton<PostgresQuotationStore>();
            services.AddSingleton<IQuotationStore>(s => s.GetRequiredService<PostgresQuotationStore>());
            services.AddSingleton<IProjectStore>(s => s.GetRequiredService<PostgresQuotationStore>());
            services.AddSingleton<IUploadStore>(s => s.GetRequiredService<PostgresQuotationStore>());
        }
        return services;
    }
}
