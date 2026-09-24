"""Свод позиций по документу: одинаковые позиции из разных помещений складываются."""

from __future__ import annotations

import re

from ..models import GroupQty, SpecItem, SummaryItem


def build_summary(items: list[SpecItem]) -> list[SummaryItem]:
    by_key: dict[tuple[str, str], SummaryItem] = {}
    order: list[tuple[str, str]] = []
    for item in items:
        key = (item.pos_key, _norm_text(item.description))
        summary = by_key.get(key)
        if summary is None:
            summary = SummaryItem(
                pos=item.pos,
                pos_key=item.pos_key,
                name=item.name,
                description=item.description,
                type_mark=item.type_mark,
                manufacturer=item.manufacturer,
                unit=item.unit,
                qty=0.0,
                section=_section_for(item),
                note=item.note,
            )
            by_key[key] = summary
            order.append(key)
        summary.item_ids.append(item.id)
        summary.groups.append(GroupQty(group=item.group, qty=item.qty))
        if item.qty is None:
            summary.qty = None if summary.qty in (None, 0.0) and len(summary.item_ids) == 1 else summary.qty
            summary.warnings.append(f"стр. {item.page}: количество не прочитано, в сумме не учтено")
        elif summary.qty is not None:
            summary.qty += item.qty
        if item.unit and summary.unit and item.unit != summary.unit:
            summary.warnings.append(f"разные единицы измерения: «{summary.unit}» и «{item.unit}»")

    result = [by_key[k] for k in order]
    _flag_duplicate_positions(result)
    return result


def _flag_duplicate_positions(summary: list[SummaryItem]) -> None:
    seen: dict[str, int] = {}
    for s in summary:
        if not s.pos_key:
            continue
        seen[s.pos_key] = seen.get(s.pos_key, 0) + 1
    for s in summary:
        if s.pos_key and seen[s.pos_key] > 1 and not s.pos_key.startswith("б"):
            s.warnings.append("одна позиция с разными описаниями — проверить, не опечатка ли в PDF")


def _section_for(item: SpecItem) -> str:
    """«Раздел» для КП: раздел документа, если он был заголовком в таблице.

    Помещения («1.01 Групповая …») разделом не считаются — они попадают в лист
    «По помещениям».
    """
    group = item.group.strip()
    if group and not re.match(r"^\d{1,2}\.\d{2}\b", group):
        return group.capitalize() if group.isupper() else group
    return ""


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()
