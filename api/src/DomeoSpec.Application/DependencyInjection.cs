using DomeoSpec.Application.Parsing;
using Microsoft.Extensions.DependencyInjection;

namespace DomeoSpec.Application;

public static class DependencyInjection
{
    /// <summary>Сценарии уровня Application — по одной строке на сценарий.</summary>
    public static IServiceCollection AddApplication(this IServiceCollection services)
    {
        services.AddScoped<ParseSpecificationHandler>();
        services.AddScoped<ExportSpecificationHandler>();
        return services;
    }
}
