using System.Diagnostics;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;

namespace DomeoSpec.Desktop;

/// <summary>Запуск и остановка бэкенда десктоп-приложения: ядро разбора (Python) и API (.NET)
/// как дочерние процессы на localhost. В автономной сборке рядом с .exe лежат папки core/, api/,
/// web/, tesseract/ (и pgsql/ на стадии БД); на машине разработки — откат на репозиторий
/// (uvicorn из core/, собранный DomeoSpec.Api.dll, web/dist).</summary>
public sealed class Backend : IAsyncDisposable
{
    private readonly List<Process> _procs = new();
    private readonly string _root = AppContext.BaseDirectory;
    private PostgresServer? _pg;

    /// <summary>Адрес интерфейса после запуска (http://127.0.0.1:порт/spec/).</summary>
    public string AppUrl { get; private set; } = "";

    /// <summary>Данные приложения: кэш цен, индекс поставщиков, БД — в профиле пользователя.</summary>
    public string DataDir { get; } =
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DomeoSpec");

    public async Task StartAsync(Action<string> status, CancellationToken ct)
    {
        Directory.CreateDirectory(DataDir);
        DiagLog.Init(Path.Combine(DataDir, "start-diag.log"));
        DiagLog.Log($"root={_root}");
        DiagLog.Log($"user={Environment.UserName} 64bit={Environment.Is64BitProcess} cwd={Environment.CurrentDirectory}");
        DiagLog.Log($"PATH={Environment.GetEnvironmentVariable("PATH")}");

        int corePort = FreePort();
        int apiPort = FreePort();
        DiagLog.Log($"corePort={corePort} apiPort={apiPort}");

        // Ядро грузится дольше всего (Python + библиотеки) — запускаем его сразу, пока поднимается БД.
        status("Запуск ядра разбора…");
        StartCore(corePort);
        DiagLog.Log($"ядро запущено, pid={_procs.LastOrDefault()?.Id}");

        string? conn = null;
        var bundlePgBin = Path.Combine(_root, "pgsql", "bin");
        if (File.Exists(Path.Combine(bundlePgBin, "pg_ctl.exe"))) // портативный PostgreSQL в комплекте
        {
            status("Запуск базы данных…");
            var (bin, data) = ResolvePostgres(bundlePgBin);  // гарантируем ASCII-путь для PostgreSQL
            DiagLog.Log($"PostgreSQL bin={bin} data={data}");
            _pg = new PostgresServer(bin, data);
            await _pg.StartAsync(status, ct);
            conn = _pg.ConnectionString;
            DiagLog.Log($"БД поднялась: {conn}");
        }
        else DiagLog.Log("pg_ctl.exe не найден — БД пропущена");

        status("Запуск сервиса…");
        StartApi(apiPort, corePort, conn);
        DiagLog.Log($"API запущен, pid={_procs.LastOrDefault()?.Id}");

        AppUrl = $"http://127.0.0.1:{apiPort}/spec/";
        status("Подготовка интерфейса…");
        try
        {
            await WaitHealthy($"http://127.0.0.1:{apiPort}/api/specifications/health", ct);
            DiagLog.Log("health OK — интерфейс готов");
        }
        catch (Exception ex) { DiagLog.Log($"health НЕ дождались: {ex.Message}"); throw; }
    }

    private void StartCore(int port)
    {
        var bundled = Path.Combine(_root, "core", "domeo-spec-core.exe");
        ProcessStartInfo psi;
        if (File.Exists(bundled))
        {
            psi = new ProcessStartInfo(bundled);
            psi.ArgumentList.Add("--port");
            psi.ArgumentList.Add(port.ToString());
        }
        else // откат для разработки: uvicorn из репозитория
        {
            psi = new ProcessStartInfo("python");
            foreach (var a in new[] { "-m", "uvicorn", "app.main:app", "--port", port.ToString(), "--app-dir", RepoPath("core") })
                psi.ArgumentList.Add(a);
        }
        psi.Environment["DATA_DIR"] = Path.Combine(DataDir, "core-data");
        psi.Environment["PRICE_SEARCH_PROVIDER"] = "auto";
        var tess = Path.Combine(_root, "tesseract");
        if (Directory.Exists(tess)) // OCR сканов: бинарник в PATH, языковые данные — через TESSDATA_PREFIX
        {
            psi.Environment["PATH"] = tess + ";" + Environment.GetEnvironmentVariable("PATH");
            psi.Environment["TESSDATA_PREFIX"] = tess;
        }
        Launch(psi);
    }

    private void StartApi(int apiPort, int corePort, string? conn)
    {
        var bundledExe = Path.Combine(_root, "api", "DomeoSpec.Api.exe");
        var bundledDll = Path.Combine(_root, "api", "DomeoSpec.Api.dll");
        var web = Directory.Exists(Path.Combine(_root, "web")) ? Path.Combine(_root, "web")
                                                               : Path.Combine(RepoPath("web"), "dist");
        ProcessStartInfo psi;
        if (File.Exists(bundledExe)) // автономная self-contained сборка API (без установленного .NET)
        {
            psi = new ProcessStartInfo(bundledExe);
        }
        else // откат для разработки: запуск собранного DLL через установленный dotnet
        {
            psi = new ProcessStartInfo("dotnet");
            psi.ArgumentList.Add(File.Exists(bundledDll) ? bundledDll : RepoApiDll());
        }
        psi.Environment["ASPNETCORE_URLS"] = $"http://127.0.0.1:{apiPort}";
        psi.Environment["ASPNETCORE_ENVIRONMENT"] = "Production";
        psi.Environment["Engine__BaseUrl"] = $"http://127.0.0.1:{corePort}";
        psi.Environment["Engine__TimeoutSeconds"] = "600";
        psi.Environment["Web__DistPath"] = web;
        // БД истории/объектов — строка подключения к портативному PostgreSQL (или из окружения).
        var quotations = conn ?? Environment.GetEnvironmentVariable("DOMEO_QUOTATIONS_CONNECTION");
        if (!string.IsNullOrWhiteSpace(quotations))
            psi.Environment["ConnectionStrings__Quotations"] = quotations;
        Launch(psi);
    }

    private void Launch(ProcessStartInfo psi)
    {
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        _procs.Add(Process.Start(psi) ?? throw new InvalidOperationException($"не удалось запустить {psi.FileName}"));
    }

    private static async Task WaitHealthy(string url, CancellationToken ct)
    {
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };
        for (var i = 0; i < 180 && !ct.IsCancellationRequested; i++)
        {
            try
            {
                if ((await http.GetAsync(url, ct)).IsSuccessStatusCode) return;
            }
            catch { /* бэкенд ещё поднимается */ }
            await Task.Delay(500, ct);
        }
        throw new TimeoutException("бэкенд не ответил вовремя");
    }

    private static int FreePort()
    {
        var l = new TcpListener(IPAddress.Loopback, 0);
        l.Start();
        var port = ((IPEndPoint)l.LocalEndpoint).Port;
        l.Stop();
        return port;
    }

    // PostgreSQL на Windows не работает из пути с не-ASCII символами — ломаются и данные, и сами
    // бинарники (в share/ лежат файлы локали/кодировок). Если приложение распаковано в папку с
    // кириллицей или у пользователя кириллическое имя профиля (частый случай) — переносим кластер
    // и, при необходимости, бинарники PostgreSQL в гарантированно ASCII-расположение
    // (C:\ProgramData\DomeoSpec). Так приложение работает, куда бы его ни распаковали.
    private (string bin, string data) ResolvePostgres(string bundlePgBin)
    {
        var localData = Path.Combine(DataDir, "pgdata");
        if (IsAscii(bundlePgBin) && IsAscii(localData))
            return (bundlePgBin, localData);  // всё ASCII — работаем на месте, данные в профиле

        var asciiBase = AsciiDataBase();
        var data = Path.Combine(asciiBase, "pgdata");
        var bin = bundlePgBin;
        if (!IsAscii(bundlePgBin))  // бинарники в кириллическом пути — копируем их в ASCII (один раз)
        {
            var dest = Path.Combine(asciiBase, "pgsql");
            bin = Path.Combine(dest, "bin");
            if (!File.Exists(Path.Combine(bin, "pg_ctl.exe")))
                CopyDir(Path.GetDirectoryName(bundlePgBin)!, dest);  // bundle\pgsql -> asciiBase\pgsql
        }
        return (bin, data);
    }

    private static bool IsAscii(string path)
    {
        foreach (var c in path)
            if (c > '\x7f') return false;
        return true;
    }

    private static string AsciiDataBase()
    {
        var common = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "DomeoSpec");
        return IsAscii(common) ? common : @"C:\DomeoSpecData";  // ProgramData почти всегда ASCII; на всякий случай — корень диска
    }

    private static void CopyDir(string src, string dst)
    {
        src = Path.GetFullPath(src);
        dst = Path.GetFullPath(dst);
        Directory.CreateDirectory(dst);
        foreach (var file in Directory.GetFiles(src, "*", SearchOption.AllDirectories))
        {
            var target = Path.Combine(dst, Path.GetRelativePath(src, file));
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            File.Copy(file, target, overwrite: true);
        }
    }

    // Пути репозитория — для запуска на машине разработки (exe в desktop/.../bin/Debug/net9.0-windows/).
    private string RepoPath(string sub) => Path.GetFullPath(Path.Combine(_root, "..", "..", "..", "..", "..", sub));
    private string RepoApiDll() =>
        Path.Combine(RepoPath("api"), "src", "DomeoSpec.Api", "bin", "Debug", "net9.0", "DomeoSpec.Api.dll");

    public ValueTask DisposeAsync()
    {
        _pg?.Stop();  // корректно останавливаем кластер PostgreSQL
        foreach (var p in _procs)
        {
            try
            {
                if (!p.HasExited) p.Kill(entireProcessTree: true);
            }
            catch { /* уже завершился */ }
        }
        return ValueTask.CompletedTask;
    }
}
