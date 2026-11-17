using System.Net;
using System.Net.Sockets;
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

// Доп. loopback-порт для браузерного расширения Domeo (мост «цена с маркетплейса → строка спеки»,
// ExtensionBridgeController). Слушаем ТОЛЬКО 127.0.0.1 и ТОЛЬКО если порт свободен — занятость порта
// не должна ронять запуск API/десктопа. Случайный адрес UI (ASPNETCORE_URLS из десктопа) сохраняем.
// В тестах (WebApplicationFactory) не трогаем — там свой сервер.
if (!builder.Environment.IsEnvironment("Testing"))
{
    var bridgePort = builder.Configuration.GetValue("Extension:BridgePort", 8777);
    if (bridgePort > 0 && BridgePortFree(bridgePort))
    {
        var bridgeUrl = $"http://127.0.0.1:{bridgePort}";
        var uiUrls = builder.Configuration["urls"]
                     ?? builder.Configuration["ASPNETCORE_URLS"]
                     ?? Environment.GetEnvironmentVariable("ASPNETCORE_URLS");
        builder.WebHost.UseUrls(string.IsNullOrWhiteSpace(uiUrls)
            ? [bridgeUrl]
            : [.. uiUrls.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                        .Where(u => !u.Contains($":{bridgePort}")), bridgeUrl]);
    }
}

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

// Состояние моста браузерного расширения (почтовый ящик UI ↔ расширение), см. ExtensionBridgeController.
builder.Services.AddSingleton<DomeoSpec.Api.Extension.ExtensionBridgeState>();

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

// Порт свободен? Проверяем до привязки моста, чтобы занятость 8777 не уронила запуск приложения.
static bool BridgePortFree(int port)
{
    try
    {
        var listener = new TcpListener(IPAddress.Loopback, port);
        listener.Start();
        listener.Stop();
        return true;
    }
    catch (SocketException) { return false; }
}

/// <summary>Точка входа видна тестам (WebApplicationFactory&lt;Program&gt;).</summary>
public partial class Program;
