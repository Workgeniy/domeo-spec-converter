using DomeoSpec.Application.Parsing;
using DomeoSpec.Application.Pricing;
using Microsoft.Extensions.DependencyInjection;

namespace DomeoSpec.Application;

public static class DependencyInjection
{
    /// <summary>Сценарии уровня Application — по одной строке на сценарий.</summary>
    public static IServiceCollection AddApplication(this IServiceCollection services)
    {
        services.AddScoped<ParseSpecificationHandler>();
        services.AddScoped<CheckDrawingHandler>();
        services.AddScoped<ExportSpecificationHandler>();
        services.AddScoped<UploadPriceListHandler>();
        services.AddScoped<MatchPriceListHandler>();
        services.AddScoped<LookupInternetHandler>();
        services.AddScoped<AddSupplierHandler>();
        services.AddScoped<UploadSupplierPriceListHandler>();
        services.AddScoped<UpdateSupplierHandler>();
        services.AddScoped<SetIndexationHandler>();
        services.AddScoped<DomeoSpec.Application.Quotations.SaveQuotationHandler>();
        services.AddScoped<DomeoSpec.Application.Quotations.SaveProjectHandler>();
        services.AddScoped<DomeoSpec.Application.Uploads.SaveUploadHandler>();
        services.AddScoped<DomeoSpec.Application.Uploads.ParseUploadHandler>();
        return services;
    }
}
