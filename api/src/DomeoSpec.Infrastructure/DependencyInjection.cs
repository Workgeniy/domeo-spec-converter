using DomeoSpec.Application.Parsing;
using DomeoSpec.Application.Pricing;
using DomeoSpec.Infrastructure.Engine;
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
        return services;
    }
}
