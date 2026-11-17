using DomeoSpec.Api.Extension;
using DomeoSpec.Application.Common;
using Microsoft.AspNetCore.Mvc;

namespace DomeoSpec.Api.Controllers;

/// <summary>Мост браузерного расширения Domeo (цены с маркетплейсов). Приложение слушает его на
/// фикс-порту 127.0.0.1:8777 (см. Program.cs), чтобы расширение находило приложение, не зная
/// случайного порта UI. Работает как почтовый ящик: веб-интерфейс кладёт открытую спеку, расширение
/// её читает и присылает найденные цены, веб-интерфейс забирает их и раскладывает по строкам.
/// CORS не нужен — расширение ходит сюда из своего service worker (host_permissions на 127.0.0.1).</summary>
[ApiController]
[Route("ext")]
public sealed class ExtensionBridgeController(ExtensionBridgeState state) : ControllerBase
{
    /// <summary>Обнаружение/здоровье: расширение проверяет, что приложение на связи.</summary>
    [HttpGet("ping")]
    public ActionResult<ApiResponse<BridgePing>> Ping() =>
        ApiResponse<BridgePing>.Ok(new BridgePing("domeo", "1"));

    /// <summary>Текущая спека — её читает расширение для списка «→ строку».</summary>
    [HttpGet("spec/current")]
    public ActionResult<ApiResponse<BridgeSpec>> GetSpec() =>
        ApiResponse<BridgeSpec>.Ok(new BridgeSpec(state.CurrentSpec));

    /// <summary>Веб-интерфейс сообщает, какую спеку открыл пользователь.</summary>
    [HttpPost("spec/current")]
    public ActionResult<ApiResponse<BridgeSpec>> SetSpec([FromBody] IReadOnlyList<BridgeSpecLine>? items)
    {
        state.CurrentSpec = items ?? [];
        return ApiResponse<BridgeSpec>.Ok(new BridgeSpec(state.CurrentSpec));
    }

    /// <summary>Расширение прислало найденную цену для строки спеки.</summary>
    [HttpPost("price")]
    public ActionResult<ApiResponse<BridgeAck>> AddPrice([FromBody] BridgeFoundPrice price)
    {
        if (string.IsNullOrWhiteSpace(price.Name))
            throw new ValidationFailedException("Пустая цена: нет названия товара.");
        state.AddPrice(price);
        return ApiResponse<BridgeAck>.Ok(new BridgeAck(true));
    }

    /// <summary>Веб-интерфейс забирает накопленные цены (очередь очищается).</summary>
    [HttpGet("prices")]
    public ActionResult<ApiResponse<IReadOnlyList<BridgeFoundPrice>>> DrainPrices() =>
        ApiResponse<IReadOnlyList<BridgeFoundPrice>>.Ok(state.DrainPrices());
}

public sealed record BridgePing(string App, string Version);
public sealed record BridgeSpec(IReadOnlyList<BridgeSpecLine> Items);
public sealed record BridgeAck(bool Ok);
