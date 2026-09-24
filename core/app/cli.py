"""Запуск из командной строки: python -m app.cli <файл.pdf> [выход.xlsx]"""

from __future__ import annotations

import sys
from pathlib import Path

from .export.excel import build_workbook
from .models import ExportRequest
from .parsing.spec_parser import parse_pdf


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    pdf = Path(argv[1])
    out = Path(argv[2]) if len(argv) > 2 else pdf.with_suffix(".xlsx")
    doc = parse_pdf(pdf)
    spec_pages = [p for p in doc.pages if p.kind == "spec"]
    print(f"{doc.file_name}: шифр {doc.doc_code}; страниц со спецификацией {len(spec_pages)}; "
          f"строк {len(doc.items)}; позиций в своде {len(doc.summary)}")
    warned = [i for i in doc.items if i.warnings]
    print(f"строк с предупреждениями: {len(warned)}")
    for item in warned[:15]:
        print(f"  стр.{item.page} поз.{item.pos!r}: {'; '.join(item.warnings)}")
    for p in doc.pages:
        for w in p.warnings:
            print(f"  стр.{p.number}: {w}")
    wb = build_workbook(ExportRequest(**doc.model_dump()))
    wb.save(out)
    print("сохранено:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
