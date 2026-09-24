namespace DomeoSpec.Domain.Specifications;

/// <summary>
/// Разобранный том ТХ: страницы, строки спецификации как в PDF и свод по позициям.
/// Модель повторяет контракт ядра разбора (core/app/models.py); имена полей в JSON — snake_case.
/// </summary>
public sealed record ParsedDocument
{
    public string FileName { get; init; } = "";
    /// <summary>Шифр документа, например «ДОО350-ДОН-ПИР-П-ТХ1».</summary>
    public string DocCode { get; init; } = "";
    /// <summary>Наименование объекта.</summary>
    public string Title { get; init; } = "";
    /// <summary>Название спецификации («Спецификация технологического оборудования …»).</summary>
    public string SpecTitle { get; init; } = "";
    public IReadOnlyList<PageInfo> Pages { get; init; } = [];
    public IReadOnlyList<SpecItem> Items { get; init; } = [];
    public IReadOnlyList<SummaryItem> Summary { get; init; } = [];
    public IReadOnlyList<string> Warnings { get; init; } = [];
}

/// <summary>Одна строка спецификации в том виде, в каком она стоит в PDF.</summary>
public sealed record SpecItem
{
    public int Id { get; init; }
    public int Page { get; init; }
    /// <summary>Позиция как в документе: «2.10», «1,10б».</summary>
    public string Pos { get; init; } = "";
    /// <summary>Нормализованная позиция для группировки: «2.10», «1.10б».</summary>
    public string PosKey { get; init; } = "";
    /// <summary>Краткое наименование (первое предложение описания).</summary>
    public string Name { get; init; } = "";
    /// <summary>Полный текст графы «Наименование и техническая характеристика».</summary>
    public string Description { get; init; } = "";
    public string TypeMark { get; init; } = "";
    public string Code { get; init; } = "";
    public string Manufacturer { get; init; } = "";
    public string Unit { get; init; } = "";
    public double? Qty { get; init; }
    public string QtyRaw { get; init; } = "";
    public string Mass { get; init; } = "";
    public string Note { get; init; } = "";
    /// <summary>Помещение или раздел, к которому относится строка.</summary>
    public string Group { get; init; } = "";
    public IReadOnlyList<string> Warnings { get; init; } = [];
}

/// <summary>Позиция, сведённая по всему документу (одна строка на позицию).</summary>
public sealed record SummaryItem
{
    public string Pos { get; init; } = "";
    public string PosKey { get; init; } = "";
    public string Name { get; init; } = "";
    public string Description { get; init; } = "";
    public string TypeMark { get; init; } = "";
    public string Manufacturer { get; init; } = "";
    public string Unit { get; init; } = "";
    public double? Qty { get; init; }
    /// <summary>«Раздел» в КП.</summary>
    public string Section { get; init; } = "";
    public string Note { get; init; } = "";
    public IReadOnlyList<GroupQty> Groups { get; init; } = [];
    public IReadOnlyList<int> ItemIds { get; init; } = [];
    public IReadOnlyList<string> Warnings { get; init; } = [];
}

public sealed record GroupQty
{
    public string Group { get; init; } = "";
    public double? Qty { get; init; }
}

public sealed record PageInfo
{
    public int Number { get; init; }
    /// <summary>spec | other.</summary>
    public string Kind { get; init; } = "other";
    /// <summary>text | ocr | skipped.</summary>
    public string Source { get; init; } = "text";
    public int Rows { get; init; }
    public IReadOnlyList<string> Warnings { get; init; } = [];
}
