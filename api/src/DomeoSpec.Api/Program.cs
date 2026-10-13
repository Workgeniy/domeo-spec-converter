using System.Text.Json;
using DomeoSpec.Api.Infrastructure;
using DomeoSpec.Application;
using DomeoSpec.Application.Common;
using DomeoSpec.Infrastructure;
using Microsoft.AspNetCore.Http.Features;

var builder = WebApplication.CreateBuilder(args);
// Локальные реквизиты БД не попадают в Git или Docker-образ; переменные среды приоритетнее.
if (builder.Environment.IsDevelopment())
    builder.Configuration.AddJsonFile("appsettings.Local.json", optional: true).AddEnvironmentVariables();

// --- Services -----------------------------------------------------------------

// snake_case во всём JSON: так контракт фронта совпадает с контрактом ядра, и типы в web/src/api.ts
// описаны один раз.
builder.Services.AddControllers().AddJsonOptions(o =>
{
    o.JsonSerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower;
});

// Загрузка тома до 100 МБ (ограничение сценария — в ParseSpecificationHandler).
builder.Services.Configure<FormOptions>(o => o.MultipartBodyLengthLimit = 100L * 1024 * 1024);
builder.WebHost.ConfigureKestrel(o => o.Limits.MaxRequestBodySize = 100L * 1024 * 1024);

builder.Services.AddInfrastructure(builder.Configuration);
builder.Services.AddApplication();

// RFC 7807 для любой ошибки; поле code — у каждого ProblemDetails, включая те, что формирует фреймворк.
builder.Services.AddProblemDetails(options => options.CustomizeProblemDetails = context =>
{
    if (!context.ProblemDetails.Extensions.ContainsKey("code"))
        context.ProblemDetails.Extensions["code"] =
            ErrorCodes.ForStatus(context.ProblemDetails.Status ?? context.HttpContext.Response.StatusCode);
});
builder.Services.AddExceptionHandler<GlobalExceptionHandler>();

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

var app = builder.Build();

// --- Pipeline -----------------------------------------------------------------

app.UseExceptionHandler();
app.UseStatusCodePages();

if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.MapControllers();

// Собранный фронт раздаётся этим же процессом; в разработке фронт живёт на Vite и проксирует
// /api сюда. Путь к сборке — Web:DistPath (в образе /app/wwwroot), по умолчанию web/dist
// рядом с репозиторием. Всё, что не /api и не файл, — SPA.
var webDist = app.Configuration["Web:DistPath"]
              ?? Path.GetFullPath(Path.Combine(app.Environment.ContentRootPath, "..", "..", "..", "web", "dist"));
if (Directory.Exists(webDist))
{
    var files = new Microsoft.Extensions.FileProviders.PhysicalFileProvider(webDist);
    app.UseDefaultFiles(new DefaultFilesOptions { FileProvider = files });
    app.UseStaticFiles(new StaticFileOptions { FileProvider = files });
    app.MapFallbackToFile("index.html", new StaticFileOptions { FileProvider = files });
}

app.Run();

/// <summary>Точка входа видна тестам (WebApplicationFactory&lt;Program&gt;).</summary>
public partial class Program;
