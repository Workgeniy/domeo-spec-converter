namespace DomeoSpec.Api.Extension;

/// <summary>Состояние моста браузерного расширения в памяти процесса: текущая спека (её кладёт
/// веб-интерфейс, читает расширение) и очередь найденных цен (их шлёт расширение, забирает
/// веб-интерфейс). Singleton — живёт между запросами, не переживает перезапуск. Доступ под замком:
/// к мосту одновременно обращаются и UI, и расширение.</summary>
public sealed class ExtensionBridgeState
{
    private readonly object _lock = new();
    private IReadOnlyList<BridgeSpecLine> _spec = [];
    private readonly List<BridgeFoundPrice> _prices = [];

    /// <summary>Открытая пользователем спека — для выпадающего списка «→ строку» в расширении.</summary>
    public IReadOnlyList<BridgeSpecLine> CurrentSpec
    {
        get { lock (_lock) { return _spec; } }
        set { lock (_lock) { _spec = value; } }
    }

    public void AddPrice(BridgeFoundPrice price)
    {
        lock (_lock) { _prices.Add(price); }
    }

    /// <summary>Отдать накопленные цены и очистить очередь — веб-интерфейс забирает их пачкой.</summary>
    public IReadOnlyList<BridgeFoundPrice> DrainPrices()
    {
        lock (_lock)
        {
            var copy = _prices.ToArray();
            _prices.Clear();
            return copy;
        }
    }
}

/// <summary>Строка спецификации, которую расширение показывает в списке «→ строку».
/// Кол-во — дробное: в спецификациях встречаются площади/погонные метры (например, 2,5).</summary>
public sealed record BridgeSpecLine(string Id, string Name, double Qty = 0);

/// <summary>Найденная расширением цена на маркетплейсе для конкретной строки спеки.</summary>
public sealed record BridgeFoundPrice(
    string SpecItemId,
    string Source,
    string Name,
    int Price,
    string? ArticleId = null,
    string? Url = null,
    int? OldPrice = null,
    string? Seller = null,
    string? Brand = null,
    double? Rating = null,
    int? Reviews = null);
