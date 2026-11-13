using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace DomeoSpec.Desktop;

/// <summary>Главное окно: запускает бэкенд, затем показывает интерфейс в WebView2.</summary>
public sealed class MainForm : Form
{
    private readonly WebView2 _web = new() { Dock = DockStyle.Fill };
    private readonly Label _status = new()
    {
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleCenter,
        Font = new Font("Segoe UI", 12F),
    };
    private readonly Backend _backend = new();

    public MainForm()
    {
        Text = "Domeo — просчёт спецификаций";
        Width = 1400;
        Height = 900;
        StartPosition = FormStartPosition.CenterScreen;
        _status.Text = "Запуск…";
        Controls.Add(_status);
        Shown += OnShown;
        FormClosed += async (_, _) => await _backend.DisposeAsync();
    }

    private async void OnShown(object? sender, EventArgs e)
    {
        if (!WebView2Available())  // без Edge WebView2 Runtime окно не отрисуется — подсказываем, что ставить
        {
            _status.Text =
                "Для работы приложения нужен компонент\n«Microsoft Edge WebView2 Runtime» (бесплатный, от Microsoft).\n\n" +
                "Скачайте «Evergreen Standalone Installer» и установите:\n" +
                "https://developer.microsoft.com/microsoft-edge/webview2/\n\n" +
                "После установки запустите Domeo снова.";
            return;
        }
        try
        {
            // Поднимаем бэкенд в фоновом потоке: запуск БД/ядра блокирующий, и на UI-потоке окно
            // «замерзало» бы на эти секунды (выглядит как зависание, пользователь жмёт запуск второй раз).
            await Task.Run(() => _backend.StartAsync(s => BeginInvoke(() => _status.Text = s), CancellationToken.None));
            var env = await CoreWebView2Environment.CreateAsync(userDataFolder: Path.Combine(_backend.DataDir, "webview"));
            await _web.EnsureCoreWebView2Async(env);
            Controls.Remove(_status);
            Controls.Add(_web);
            _web.Source = new Uri(_backend.AppUrl);
            _ = Updater.CheckInBackgroundAsync();  // фоновая проверка обновлений — работе не мешает
        }
        catch (Exception ex)
        {
            DiagLog.Log($"СБОЙ запуска: {ex}");
            _status.Text = "Не удалось запустить приложение:\n" + ex.Message +
                "\n\nПодробности — в файле %LOCALAPPDATA%\\DomeoSpec\\start-diag.log";
        }
    }

    private static bool WebView2Available()
    {
        try { return !string.IsNullOrEmpty(CoreWebView2Environment.GetAvailableBrowserVersionString()); }
        catch { return false; }  // рантайм не установлен
    }
}
