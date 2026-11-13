using System.Threading;
using Velopack;

namespace DomeoSpec.Desktop;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        // Velopack обрабатывает установку/обновление/удаление: при этих операциях процесс
        // запускается с особыми аргументами, которые этот вызов отрабатывает и завершает процесс.
        // Поэтому он обязан стоять самым первым в Main, до любой другой логики.
        VelopackApp.Build().Run();

        // Один экземпляр: второй запуск поднял бы вторую БД на тот же кластер — они конфликтуют,
        // и оба окна зависают. Если приложение уже открыто — сообщаем и выходим.
        using var mutex = new Mutex(initiallyOwned: true, name: @"Local\DomeoSpecDesktopSingleInstance", out bool created);
        if (!created)
        {
            MessageBox.Show("Domeo уже запущен — переключитесь на открытое окно.", "Domeo",
                MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        ApplicationConfiguration.Initialize();
        Application.Run(new MainForm());
    }
}
