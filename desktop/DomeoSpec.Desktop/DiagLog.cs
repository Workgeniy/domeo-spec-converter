namespace DomeoSpec.Desktop;

/// <summary>Простой журнал запуска: пишет стадии старта и ошибки в файл рядом с данными
/// (%LOCALAPPDATA%\DomeoSpec\start-diag.log), чтобы разобрать сбой, который не воспроизводится.
/// Дозапись с общим доступом — чтобы параллельное чтение файла не мешало записи, а записи
/// разных запусков накапливались, а не затирали друг друга.</summary>
internal static class DiagLog
{
    private static string? _path;
    private static readonly object _lock = new();

    public static void Init(string path)
    {
        _path = path;
        try { Directory.CreateDirectory(Path.GetDirectoryName(path)!); } catch { }
        Write($"=== запуск {DateTime.Now:yyyy-MM-dd HH:mm:ss} (pid {Environment.ProcessId}) ===");
    }

    public static void Log(string message) => Write($"{DateTime.Now:HH:mm:ss.fff} {message}");

    private static void Write(string line)
    {
        if (_path is null) return;
        lock (_lock)
        {
            try
            {
                using var fs = new FileStream(_path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite);
                using var w = new StreamWriter(fs);
                w.WriteLine(line);
            }
            catch { /* журнал не критичен */ }
        }
    }

    /// <summary>Последние строки файла (для хвоста server.log при сбое).</summary>
    public static string Tail(string file, int lines = 12)
    {
        try { return "\r\n  " + string.Join("\r\n  ", File.ReadLines(file).Reverse().Take(lines).Reverse()); }
        catch { return "(нет)"; }
    }
}
