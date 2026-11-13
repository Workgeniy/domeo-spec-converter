using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace DomeoSpec.Desktop;

/// <summary>Главное окно: запускает бэкенд и показывает интерфейс в WebView2. Сверху — полоса
/// уведомления об обновлении (появляется, когда оно скачано), снизу — строка состояния с версией
/// и кнопкой ручной проверки обновлений.</summary>
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
    private readonly Updater _updater = new();

    // Полоса «доступно обновление» — сверху, скрыта, пока обновления нет.
    private readonly Panel _updateBar = new() { Dock = DockStyle.Top, Height = 46, Visible = false, BackColor = Color.FromArgb(255, 247, 214) };
    private readonly Label _updateText = new() { Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, Font = new Font("Segoe UI", 10F), Padding = new Padding(14, 0, 0, 0) };
    private readonly Button _updateApply = new() { Text = "Обновить и перезапустить", Dock = DockStyle.Right, Width = 210, FlatStyle = FlatStyle.System };
    private readonly Button _updateLater = new() { Text = "Позже", Dock = DockStyle.Right, Width = 90, FlatStyle = FlatStyle.System };

    // Строка состояния — снизу: версия + статус + кнопка ручной проверки.
    private readonly Panel _statusBar = new() { Dock = DockStyle.Bottom, Height = 28, BackColor = SystemColors.Control };
    private readonly Label _verLabel = new() { Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, Font = new Font("Segoe UI", 8.5F), ForeColor = SystemColors.GrayText, Padding = new Padding(12, 0, 0, 0) };
    private readonly Button _checkButton = new() { Text = "Проверить обновления", Dock = DockStyle.Right, Width = 180, FlatStyle = FlatStyle.System };

    public MainForm()
    {
        Text = "Domeo — просчёт спецификаций";
        Width = 1400;
        Height = 900;
        StartPosition = FormStartPosition.CenterScreen;

        // Полоса обновления: [текст .... «Позже» «Обновить и перезапустить»].
        _updateApply.Click += OnUpdateApply;
        _updateLater.Click += (_, _) => { _updater.ApplyOnExit(); _updateBar.Visible = false; SetStatus("обновление установится при закрытии"); };
        _updateBar.Controls.Add(_updateApply);
        _updateBar.Controls.Add(_updateLater);
        _updateBar.Controls.Add(_updateText);

        // Строка состояния: [версия/статус .... «Проверить обновления»].
        _checkButton.Click += async (_, _) => { _checkButton.Enabled = false; await CheckUpdatesAsync(); _checkButton.Enabled = true; };
        _statusBar.Controls.Add(_checkButton);
        _statusBar.Controls.Add(_verLabel);

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
            // Fill-контрол добавляем ПОСЛЕДНИМ, чтобы он занял остаток между верхней и нижней полосами.
            Controls.Add(_statusBar);
            Controls.Add(_updateBar);
            Controls.Add(_web);
            _web.Source = new Uri(_backend.AppUrl);
            SetStatus("");
            _ = CheckUpdatesAsync();  // фоновая проверка обновлений при запуске — работе не мешает
        }
        catch (Exception ex)
        {
            DiagLog.Log($"СБОЙ запуска: {ex}");
            _status.Text = "Не удалось запустить приложение:\n" + ex.Message +
                "\n\nПодробности — в файле %LOCALAPPDATA%\\DomeoSpec\\start-diag.log";
        }
    }

    private async void OnUpdateApply(object? sender, EventArgs e)
    {
        _updateApply.Enabled = false;
        _updateText.Text = "Устанавливаю обновление…";
        await _backend.DisposeAsync();  // гасим ядро/API, чтобы не осталось висеть после перезапуска
        _updater.ApplyAndRestart();      // установит обновление и перезапустит Domeo в новой версии
    }

    private Task CheckUpdatesAsync() => _updater.CheckAsync(
        onStatus: s => BeginInvoke(() => SetStatus(s)),
        onReady: ver => BeginInvoke(() =>
        {
            _updateText.Text = $"Доступно обновление Domeo {ver}.";
            _updateBar.Visible = true;
        }));

    private void SetStatus(string s) =>
        _verLabel.Text = string.IsNullOrEmpty(s) ? $"Domeo {_updater.CurrentVersion}" : $"Domeo {_updater.CurrentVersion}  —  {s}";

    private static bool WebView2Available()
    {
        try { return !string.IsNullOrEmpty(CoreWebView2Environment.GetAvailableBrowserVersionString()); }
        catch { return false; }  // рантайм не установлен
    }
}
