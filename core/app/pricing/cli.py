"""Прайс закупки из командной строки.

    python -m app.pricing.cli build  история.xlsx  прайс.json      # собрать прайс
    python -m app.pricing.cli match  прайс.json  том-ТХ.pdf         # покрытие спецификации прайсом
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from ..parsing.spec_parser import parse_pdf
from .matching import Matcher
from .pricelist import PriceList, build_from_file, dump_json, summary


def main(argv: list[str]) -> int:
    if len(argv) < 4 or argv[1] not in ("build", "match"):
        print(__doc__)
        return 1
    if argv[1] == "build":
        price_list = build_from_file(argv[2])
        price_list.save(argv[3])
        print(dump_json(summary(price_list)))
        print("сохранено:", argv[3])
        return 0

    price_list = PriceList.load(argv[2])
    matcher = Matcher(price_list)
    doc = parse_pdf(Path(argv[3]))
    kinds: Counter[str] = Counter()
    for item in doc.summary:
        m = matcher.match(item.name, item.description)
        kinds[m.kind] += 1
        if m.kind in ("analog", "none"):
            best = f"{m.best.name[:45]!r} ({m.best.score:.2f})" if m.best else "—"
            print(f"  [{m.kind:6}] {item.name[:50]!r} → {best}")
    total = len(doc.summary)
    print(f"{doc.doc_code}: позиций {total}; " + ", ".join(f"{k} {v} ({v * 100 // total}%)" for k, v in kinds.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
