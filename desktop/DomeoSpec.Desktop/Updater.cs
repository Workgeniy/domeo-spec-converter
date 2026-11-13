using Velopack;
using Velopack.Sources;

namespace DomeoSpec.Desktop;

/// <summary>Авто-обновление с публичных GitHub Releases (Velopack, репозиторий
/// Workgeniy/domeo-spec-converter — токен не нужен). Проверка при запуске и по кнопке; найдя новую
/// версию, скачиваем её и сообщаем окну, чтобы показать кнопку «Обновить». Установка — по кнопке
/// (с перезапуском) или при выходе. В не установленной через Setup.exe сборке (дев/портатив) — no-op.</summary>
internal sealed class Updater
{
    private const string RepoUrl = "https://github.com/Workgeniy/domeo-spec-converter";
    private readonly UpdateManager _mgr = new(new GithubSource(RepoUrl, null, false));
    private UpdateInfo? _ready;  // скачанное обновление, готовое к установке

    public bool IsInstalled => _mgr.IsInstalled;
    public string CurrentVersion => _mgr.CurrentVersion?.ToString() ?? "дев-сборка";

    /// <summary>Проверить обновления и, если есть, скачать. onStatus — короткий статус для строки
    /// состояния; onReady(версия) — когда обновление скачано и готово к установке.</summary>
    public async Task CheckAsync(Action<string> onStatus, Action<string> onReady)
    {
        if (!_mgr.IsInstalled)
        {
            onStatus("обновления доступны только в установленной версии");
            return;
        }
        try
        {
            onStatus("проверка обновлений…");
            var info = await _mgr.CheckForUpdatesAsync();
            if (info is null)
            {
                onStatus("установлена последняя версия");
                return;
            }
            var ver = info.TargetFullRelease.Version.ToString();
            onStatus($"скачивание обновления {ver}…");
            await _mgr.DownloadUpdatesAsync(info);
            _ready = info;
            onStatus($"обновление {ver} готово к установке");
            onReady(ver);
        }
        catch (Exception ex)
        {
            onStatus("не удалось проверить обновления (нет сети?)");
            DiagLog.Log($"проверка обновлений не удалась: {ex.Message}");
        }
    }

    /// <summary>Установить скачанное обновление и перезапустить приложение.</summary>
    public void ApplyAndRestart()
    {
        if (_ready is not null)
            _mgr.ApplyUpdatesAndRestart(_ready);
    }

    /// <summary>Отложить: установить скачанное обновление при выходе — следующий запуск будет новым.</summary>
    public void ApplyOnExit()
    {
        if (_ready is not null)
            _mgr.WaitExitThenApplyUpdates(_ready, silent: true, restart: false);
    }
}
