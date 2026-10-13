namespace DomeoSpec.Domain.Specifications;

public sealed record DrawingText
{
    public IReadOnlyList<DrawingPage> Pages { get; init; } = [];
}
public sealed record DrawingPage
{
    public int Number { get; init; }
    public string SkippedReason { get; init; } = "";
    public IReadOnlyList<DrawingLine> Lines { get; init; } = [];
}
public sealed record DrawingLine
{
    public string Text { get; init; } = "";
    public double X { get; init; }
    public double Y { get; init; }
}
public sealed record DrawingHit(int Page, string Text, double X, double Y, int Count);
public sealed record DrawingCheckRow(string Pos, string Name, double? Expected, string Unit,
    int Found, string Status, IReadOnlyList<DrawingHit> Hits);
public sealed record DrawingCheckResult(IReadOnlyList<DrawingCheckRow> Rows,
    IReadOnlyList<string> UnknownLabels, IReadOnlyList<string> Warnings);
