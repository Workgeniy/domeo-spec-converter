using Velopack;
using Velopack.Sources;

namespace DomeoSpec.Desktop;

/// <summary>Авто-обновление с GitHub Releases (репозиторий Workgeniy/domeo-spec-converter —
/// публичный, токен не нужен). Проверяем при запуске в фоне; найдя новую версию, тихо скачиваем
/// её и применяем при выходе — следующий запуск Domeo будет уже обновлённым, работу не прерываем.
/// В портативной/отладочной (не установленной через Setup.exe) сборке ничего не делаем.</summary>
internal static class Updater
{
    private const string RepoUrl = "https://github.com/Workgeniy/domeo-spec-converter";

    public static async Task CheckInBackgroundAsync()
    {
        try
        {
            var mgr = new UpdateManager(new GithubSource(RepoUrl, null, false));
            if (!mgr.IsInstalled)
                return;  // запуск не из установленной версии (дев/портатив) — обновлять нечего
            var info = await mgr.CheckForUpdatesAsync();
            if (info is null)
                return;  // уже последняя версия
            await mgr.DownloadUpdatesAsync(info);
            // Применить при выходе, без перезапуска: обновление встанет к следующему запуску.
            mgr.WaitExitThenApplyUpdates(info, silent: true, restart: false);
            DiagLog.Log($"обновление {info.TargetFullRelease?.Version} скачано — встанет при следующем запуске");
        }
        catch (Exception ex)
        {
            // Нет сети / GitHub недоступен / релизов ещё нет — не мешаем работе, повторим позже.
            DiagLog.Log($"проверка обновлений не удалась: {ex.Message}");
        }
    }
}
