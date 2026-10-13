using System.Text.RegularExpressions;
using DomeoSpec.Application.Common;
using DomeoSpec.Domain.Specifications;

namespace DomeoSpec.Application.Parsing;

public sealed class CheckDrawingHandler(IParsingEngine engine)
{
    // Только самостоятельные подписи. Размеры «1000х600», даты, оси и длинные тексты не считаем.
    private static readonly Regex Label = new(@"^(?:поз\.?\s*)?(?<pos>[а-яa-z]{0,3}\d{1,4}(?:[.,]\d{1,4})?[а-яa-z]?)(?:\s*=\s*(?<qty>\d{1,4})\s*(?:шт\.?)?)?$", RegexOptions.IgnoreCase);
    private static string Key(string value) => value.Replace(",", ".").Replace(" ", "").Trim().ToLowerInvariant();

    public async Task<DrawingCheckResult> HandleAsync(Stream file, string fileName, long size, string pages,
        IReadOnlyList<SummaryItem> items, CancellationToken ct)
    {
        if (!fileName.EndsWith(".pdf", StringComparison.OrdinalIgnoreCase) || size <= 0 || size > 25L * 1024 * 1024)
            throw new ValidationFailedException("Выберите непустой PDF-план до 25 МБ или выделите нужные планы в отдельный файл.");
        var selected = pages.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (selected.Length is < 1 or > 20 || selected.Any(p => !int.TryParse(p, out var n) || n < 1))
            throw new ValidationFailedException("Укажите от 1 до 20 номеров страниц через запятую, например: 1, 2, 3.");
        if (items.Count == 0 || items.Count > 10000)
            throw new ValidationFailedException("Для сверки нужен список от 1 до 10000 позиций.");
        return Compare(await engine.ExtractDrawingTextAsync(file, string.Join(',', selected), ct), items);
    }

    public static DrawingCheckResult Compare(DrawingText drawing, IReadOnlyList<SummaryItem> items)
    {
        var warnings = new List<string> { "Предварительная сверка текстовых меток. Метка может быть номером помещения или размером; совпадение количества не доказывает полноту плана. Привязка к помещениям и распознавание символов не выполняются." };
        var hits = new Dictionary<string, List<DrawingHit>>();
        foreach (var page in drawing.Pages)
        {
            if (page.SkippedReason.Length > 0) { warnings.Add($"Страница {page.Number}: {page.SkippedReason}"); continue; }
            foreach (var line in page.Lines)
            {
                var match = Label.Match(line.Text.Trim());
                if (!match.Success) continue;
                var key = Key(match.Groups["pos"].Value);
                var qty = match.Groups["qty"].Success ? int.Parse(match.Groups["qty"].Value) : 1;
                if (qty <= 0) continue;
                if (!hits.TryGetValue(key, out var list)) hits[key] = list = [];
                list.Add(new DrawingHit(page.Number, line.Text, line.X, line.Y, qty));
            }
        }
        if (drawing.Pages.All(p => p.SkippedReason.Length > 0))
            warnings.Add("Все выбранные страницы пропущены. Результат не является сверкой.");
        var groups = items.GroupBy(i => Key(i.Pos)).ToArray();
        var rows = groups.Select(group =>
        {
            var list = hits.GetValueOrDefault(group.Key) ?? [];
            var item = group.First();
            var expected = group.All(i => i.Qty.HasValue) ? group.Sum(i => i.Qty!.Value) : (double?)null;
            var found = list.Sum(h => h.Count);
            var status = group.Key.Length == 0 ? "no_position" : group.Count() > 1 ? "ambiguous" :
                drawing.Pages.All(p => p.SkippedReason.Length > 0) ? "not_checked" :
                list.Count == 0 ? "not_found" : !new[] { "шт", "штука", "штук", "штуки" }.Contains(item.Unit.Trim().TrimEnd('.').ToLowerInvariant()) ? "quantity_not_comparable" :
                expected is null ? "no_quantity" : Math.Abs(expected.Value - found) < .0001 ? "match" : "difference";
            return new DrawingCheckRow(item.Pos, string.Join(" / ", group.Select(i => i.Name).Distinct()), expected, item.Unit, found, status, list);
        }).ToArray();
        var known = groups.Select(g => g.Key).ToHashSet();
        var unknown = hits.Where(pair => !known.Contains(pair.Key)).Select(p => $"{p.Key} (стр. {string.Join(", ", p.Value.Select(h => h.Page).Distinct())})").ToArray();
        return new DrawingCheckResult(rows, unknown, warnings);
    }
}
