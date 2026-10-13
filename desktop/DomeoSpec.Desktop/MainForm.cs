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
        try
        {
            await _backend.StartAsync(s => BeginInvoke(() => _status.Text = s), CancellationToken.None);
            var env = await CoreWebView2Environment.CreateAsync(userDataFolder: Path.Combine(_backend.DataDir, "webview"));
            await _web.EnsureCoreWebView2Async(env);
            Controls.Remove(_status);
            Controls.Add(_web);
            _web.Source = new Uri(_backend.AppUrl);
        }
        catch (Exception ex)
        {
            _status.Text = "Не удалось запустить приложение:\n" + ex.Message;
        }
    }
}
