namespace DomeoSpec.Infrastructure.Engine;

/// <summary>Настройки подключения к ядру разбора (секция <c>Engine</c> в конфигурации).</summary>
public sealed class EngineOptions
{
    public const string Section = "Engine";

    /// <summary>Абсолютный адрес Python-сервиса, например http://localhost:8000.</summary>
    public string BaseUrl { get; set; } = "";

    /// <summary>Разбор 100-страничного тома с OCR может занять минуты — таймаут заметно больше обычного.</summary>
    public int TimeoutSeconds { get; set; } = 600;
}
