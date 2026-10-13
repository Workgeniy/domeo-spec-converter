using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text;

namespace DomeoSpec.Desktop;

/// <summary>Портативный PostgreSQL в составе приложения: кластер инициализируется в профиле
/// пользователя при первом запуске, стартует и останавливается вместе с приложением, авторизация
/// trust только на localhost (однопользовательский десктоп). Нужен для «Истории КП» и «Объектов».</summary>
public sealed class PostgresServer
{
    private readonly string _bin;      // pgsql/bin
    private readonly string _dataDir;  // %LOCALAPPDATA%/DomeoSpec/pgdata
    private int _port;

    public string ConnectionString { get; private set; } = "";

    public PostgresServer(string bin, string dataDir)
    {
        _bin = bin;
        _dataDir = dataDir;
    }

    public async Task StartAsync(Action<string> status, CancellationToken ct)
    {
        if (!File.Exists(Path.Combine(_dataDir, "PG_VERSION")))
        {
            status("Первичная настройка базы данных…");
            Directory.CreateDirectory(Directory.GetParent(_dataDir)!.FullName);
            Run("initdb.exe", "-D", _dataDir, "-U", "postgres", "-A", "trust", "-E", "UTF8", "--no-locale");
        }
        status("Запуск базы данных…");
        _port = FreePort();
        var log = Path.Combine(_dataDir, "server.log");
        Run("pg_ctl.exe", "-D", _dataDir, "-o", $"-p {_port} -h 127.0.0.1", "-l", log, "-w", "-t", "60", "start");
        EnsureDatabase();
        ConnectionString = $"Host=127.0.0.1;Port={_port};Database=domeo;Username=postgres";
        await Task.CompletedTask;
    }

    private void EnsureDatabase()
    {
        var exists = Capture("psql.exe", "-h", "127.0.0.1", "-p", _port.ToString(), "-U", "postgres",
                             "-d", "postgres", "-tAc", "SELECT 1 FROM pg_database WHERE datname='domeo'");
        if (exists.Trim() != "1")
            Run("createdb.exe", "-h", "127.0.0.1", "-p", _port.ToString(), "-U", "postgres", "domeo");
    }

    public void Stop()
    {
        try { Run("pg_ctl.exe", "-D", _dataDir, "-m", "fast", "-w", "-t", "30", "stop"); }
        catch { /* при аварийном закрытии кластер остановится сам при следующем старте */ }
    }

    private void Run(string exe, params string[] args)
    {
        var (code, _, err) = Exec(exe, args, 120_000);
        if (code != 0)
            throw new InvalidOperationException($"{exe} завершился с кодом {code}: {err}");
    }

    private string Capture(string exe, params string[] args) => Exec(exe, args, 60_000).stdout;

    // Асинхронное чтение потоков + ожидание по таймауту. Важно: `pg_ctl start` запускает сервер,
    // который наследует хэндлы труб родителя, поэтому блокирующий ReadToEnd зависал бы навсегда —
    // здесь мы ждём завершения именно pg_ctl, а не закрытия труб.
    private (int code, string stdout, string stderr) Exec(string exe, string[] args, int timeoutMs)
    {
        using var p = Process.Start(Psi(exe, args))!;
        var so = new StringBuilder();
        var se = new StringBuilder();
        p.OutputDataReceived += (_, e) => { if (e.Data != null) so.AppendLine(e.Data); };
        p.ErrorDataReceived += (_, e) => { if (e.Data != null) se.AppendLine(e.Data); };
        p.BeginOutputReadLine();
        p.BeginErrorReadLine();
        if (!p.WaitForExit(timeoutMs))
        {
            try { p.Kill(entireProcessTree: true); } catch { /* уже завершается */ }
            throw new TimeoutException($"{exe} не завершился за {timeoutMs} мс");
        }
        return (p.ExitCode, so.ToString(), se.ToString());
    }

    private ProcessStartInfo Psi(string exe, string[] args)
    {
        var psi = new ProcessStartInfo(Path.Combine(_bin, exe))
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var a in args) psi.ArgumentList.Add(a);
        return psi;
    }

    private static int FreePort()
    {
        var l = new TcpListener(IPAddress.Loopback, 0);
        l.Start();
        var port = ((IPEndPoint)l.LocalEndpoint).Port;
        l.Stop();
        return port;
    }
}
