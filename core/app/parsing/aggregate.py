"""Свод позиций по документу: одинаковые позиции из разных помещений складываются."""

from __future__ import annotations

import re
from collections import defaultdict

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
                image=item.image,
                image_origin="file" if item.image else "",
            )
            by_key[key] = summary
            order.append(key)
        summary.item_ids.append(item.id)
        summary.groups.append(GroupQty(group=item.group, qty=item.qty))
        if not summary.image and item.image:  # картинка могла прийти с объединённой строки позиции
            summary.image = item.image
            summary.image_origin = "file"
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
    """Один и тот же номер позиции с разными описаниями — возможная опечатка, но только если это
    в одном помещении (или помещений в документе нет вовсе — плоский список). Когда номера
    повторяются в разных помещениях, это обычная нумерация по помещениям (в каждом свои 1, 2,
    3…), а не ошибка."""
    by_pos: dict[str, list[SummaryItem]] = defaultdict(list)
    for s in summary:
        if s.pos_key and not s.pos_key.startswith("б"):
            by_pos[s.pos_key].append(s)
    for items in by_pos.values():
        if len(items) < 2:
            continue
        rooms = [frozenset(g.group for g in s.groups if g.group) for s in items]
        same_room = any(rooms[i] & rooms[j] for i in range(len(rooms)) for j in range(i + 1, len(rooms)))
        if same_room or not any(rooms):
            for s in items:
                s.warnings.append("тот же номер позиции с другим описанием — проверьте, не опечатка ли")


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


def duplicate_key(item: SummaryItem) -> str:
    """Ключ совпадения позиций между томами — по наименованию, не по номеру (номера в томах
    независимы): строчные, ё→е, без пунктуации. Берём полное описание, иначе краткое имя."""
    basis = item.description or item.name
    return re.sub(r"[^a-zа-я0-9]+", " ", basis.lower().replace("ё", "е")).strip()


def cross_volume_duplicates(summary: list[SummaryItem]) -> list[list[SummaryItem]]:
    """Группы позиций с одинаковым наименованием из разных томов (``source_doc``) — такие легко
    посчитать дважды. Внутри одного тома повторов нет (они уже сведены), поэтому группа значима,
    только если охватывает минимум два разных документа."""
    groups: dict[str, list[SummaryItem]] = {}
    for item in summary:
        key = duplicate_key(item)
        if len(key) >= 3:
            groups.setdefault(key, []).append(item)
    return [items for items in groups.values() if len({i.source_doc for i in items}) >= 2]
