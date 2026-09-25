namespace DomeoSpec.Application.Common;

/// <summary>400: входные данные не прошли проверку.</summary>
public sealed class ValidationFailedException(string message) : Exception(message);

/// <summary>404: объекта (поставщика и т. п.) нет.</summary>
public sealed class NotFoundException(string message) : Exception(message);

/// <summary>422: ядро разбора не смогло обработать документ (битый PDF и т. п.). Повтор не поможет.</summary>
public sealed class EngineFailureException(string message) : Exception(message);

/// <summary>503: зависимость (ядро разбора) не отвечает — данные целы, запрос стоит повторить позже.</summary>
public sealed class ServiceUnavailableException(string message, Exception? inner = null) : Exception(message, inner);
