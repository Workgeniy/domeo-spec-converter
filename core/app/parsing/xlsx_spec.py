"""Разбор спецификации из Excel (xlsx): шапка по словам заголовков, строки — в позиции.

Как и у PDF, столбцы узнаются по словам шапки («Поз.», «Наименование», «Кол-во»…), а не по
их месту: порядок столбцов любой. Нужны минимум «Наименование» и «Количество» (и «Поз.»,
если она есть). Объединённые ячейки разворачиваются (значение из левого верхнего угла
размножается на всю область), строки-заголовки без количества считаются разделом или
помещением — ровно как в PDF.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from openpyxl import load_workbook

from ..models import PageInfo, ParsedDocument, SpecItem
from .aggregate import build_summary
from .spec_parser import DOC_CODE_RE, TITLE_RE, _default_section, normalize_pos, parse_qty, short_name

# Ключ столбца -> слова-приметы в заголовке (подстрока, в нижнем регистре). Порядок проверки
# важен: «Наименование помещения» — это раздел, а не наименование, поэтому раздел ищем раньше.
COLUMN_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("pos", ("поз", "№")),
    ("qty", ("кол", "кол-во", "колво", "колич")),  # «Кол», «Кол-во», «Количество»
    ("unit", ("ед.", "ед ", "единиц", "ед-ц")),
    ("mass", ("масса", "вес")),
    ("code", ("код",)),
    ("manufacturer", ("завод", "изготов", "производ", "поставщик")),
    ("note", ("примеч", "коммент")),
    ("type_mark", ("тип", "марка", "артикул", "модель")),
    ("doc", ("обознач",)),
    ("razdel", ("раздел",)),  # раздел КП («Мебель», «Спортивное оборудование»)
    ("group", ("помещ",)),  # помещение («Групповая комната…»)
    ("name", ("наимен", "название", "оборудован", "описан", "номенклат")),
    # Характеристики отдельным столбцом («Технические характеристики») — в описание позиции.
    # Ищется после «name», чтобы совмещённый столбец «Наименование и тех. характеристика»
    # достался наименованию, а не характеристикам.
    ("specs", ("техническ", "тех. хар", "характеристик", "параметр")),
]
REQUIRED = ("name", "qty")  # без них лист не считаем спецификацией
HEADER_SCAN_ROWS = 60
MAX_HEADER_COLS = 60  # шире — вряд ли спецификация, не перебираем лишнее


def _text(value: object) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _expand_merges(ws) -> tuple[list[list[object]], set[tuple[int, int]]]:
    """Значения листа с развёрнутыми объединениями (значение левого верхнего угла — во все
    ячейки области) и множество ячеек, заполненных этим разворотом. Разворот нужен, чтобы
    прочитать общее значение (одна цена на группу), а множество — чтобы отличить собственное
    значение строки от унаследованного: у этой спецификации «Ед.»/«Кол» объединены по
    вертикали на строку товара и строки его характеристик — значит, это одна позиция, а не
    несколько."""
    grid: list[list[object]] = [list(row) for row in ws.iter_rows(values_only=True)]
    filled: set[tuple[int, int]] = set()
    for rng in ws.merged_cells.ranges:
        top = grid[rng.min_row - 1][rng.min_col - 1] if rng.min_row - 1 < len(grid) else None
        if top is None:
            continue
        for r in range(rng.min_row - 1, min(rng.max_row, len(grid))):
            for c in range(rng.min_col - 1, rng.max_col):
                if c < len(grid[r]) and (r, c) != (rng.min_row - 1, rng.min_col - 1):
                    grid[r][c] = top
                    filled.add((r, c))
    return grid, filled


def _match_header(cells: list[str]) -> dict[str, int] | None:
    """Строка шапки -> {ключ столбца: индекс}. Каждый столбец — не больше одного ключа."""
    lower = [c.lower() for c in cells]
    mapping: dict[str, int] = {}
    used: set[int] = set()
    for key, hints in COLUMN_HINTS:
        for i, cell in enumerate(lower):
            if i in used or not cell:
                continue
            if any(h in cell for h in hints):
                mapping[key] = i
                used.add(i)
                break
    return mapping if all(k in mapping for k in REQUIRED) else None


def _find_header(grid: list[list[object]]) -> tuple[int, dict[str, int]] | None:
    """Строка шапки — первая из первых строк, где нашлись все обязательные столбцы, и при
    равенстве — с наибольшим числом узнанных столбцов (бывает двухэтажная шапка)."""
    best: tuple[int, dict[str, int]] | None = None
    for r, row in enumerate(grid[:HEADER_SCAN_ROWS]):
        cells = [_text(v) for v in row[:MAX_HEADER_COLS]]
        mapping = _match_header(cells)
        if mapping is not None and (best is None or len(mapping) > len(best[1])):
            best = (r, mapping)
    return best


def _cell(row: list[object], mapping: dict[str, int], key: str) -> str:
    i = mapping.get(key)
    return _text(row[i]) if i is not None and i < len(row) else ""


def _own(grid: list[list[object]], filled: set[tuple[int, int]], r: int, mapping: dict[str, int], key: str) -> str:
    """Собственное значение ячейки строки — пусто, если оно унаследовано из объединения сверху."""
    i = mapping.get(key)
    if i is None or i >= len(grid[r]) or (r, i) in filled:
        return ""
    return _text(grid[r][i])


# Заголовок раздела/помещения (а не характеристика товара). Строки «только наименование»
# бывают двух видов: продолжение описания товара («Габаритные размеры…», «Электропитание…») и
# заголовок помещения/раздела. Надёжный признак продолжения — вертикальное объединение
# столбцов поз./кол./ед. на строку товара и его характеристик (см. _rows_to_items). Из
# непокрытых объединением разделом считаем только похожее на помещение/раздел, остальное —
# продолжение описания (чтобы не плодить мусорные разделы из незамеченных характеристик).
SECTION = re.compile(
    r"(?:^|\s|\()(?:раздел|участок|пом\.|помещен|этаж|подвал|цокол|антресол|кровл|чердак|прачечн|постирочн|гладильн"
    r"|кладов|групп|раздевальн|туалетн|буфетн|спальн|игров|при[её]мн|коридор|тамбур|вестибюл|холл"
    r"|лестнич|кухн|моечн|разделочн|заготовочн|овощн|мясн|рыбн|мучн|горячий цех|холодный цех|цех\b"
    r"|кабинет|зал\b|комнат|санузел|умывальн|душев|постов\b|медицин|изолятор|процедурн"
    r"|прививочн|пищеблок|серверн|кастелянск|бельев|сушильн|венткамер|электрощитов|насосн|склад"
    r"|мастерск|методическ|музыкальн|физкультурн|спортивн|логопед|психолог|бассейн|веранд|терас"
    r"|лаборатор|ресепшн|ординатор|вентиляцион|тепловой узел|итп\b|уборочн)",
    re.I,
)


# Нормальный номер позиции в Excel-спецификации: целое («1», «28»), десятичное («7.197»),
# код оборудования («М10.1», «ВК-1», «П101»), «б/н». Шире, чем у PDF: там номера единообразны
# в пределах тома, а в разных разделах Excel нумерация бывает и целой, и буквенно-цифровой.
POS_OK = re.compile(r"^(?:\d{1,4}(?:[.,/\-]\d{1,4})*[а-яa-z]?|[А-ЯA-Zа-яa-z]{1,5}[.\-]?\d{1,4}(?:[.,/\-]\d{1,4})*[а-яa-z]?|б[/\\][нп])$", re.I)


def _looks_like_section(text: str) -> bool:
    # Только у начала строки: помещение/раздел начинается с такого слова («Первый этаж»,
    # «Пом. 120 …», «Групповая …»), а у характеристики ключевое слово попадалось бы в середине.
    return bool(SECTION.search(text[:32]))


def parse_xlsx(source: str | Path | bytes, file_name: str | None = None) -> ParsedDocument:
    if isinstance(source, (bytes, bytearray)):
        name = file_name or "спецификация.xlsx"
        handle: object = io.BytesIO(bytes(source))
    else:
        name = file_name or Path(source).name
        handle = str(source)
    # data_only=True берёт посчитанные значения формул; объединения разворачиваем сами,
    # поэтому read_only не используем (в нём merged_cells.ranges недоступны).
    wb = load_workbook(handle, read_only=False, data_only=True)
    result = ParsedDocument(file_name=name)
    items: list[SpecItem] = []
    razdel_by_id: dict[int, str] = {}  # id позиции → раздел КП из столбца «Раздел»
    pre_header_text: list[str] = []

    for ws in wb.worksheets:
        grid, filled = _expand_merges(ws)
        found = _find_header(grid)
        if found is None:
            continue
        header_row, mapping = found
        pre_header_text += [_text(v) for row in grid[:header_row] for v in row if _text(v)]
        sheet_items, sheet_sections = _rows_to_items(grid, filled, header_row + 1, mapping, len(items))
        items.extend(sheet_items)
        razdel_by_id.update(sheet_sections)
        result.pages.append(PageInfo(number=len(result.pages) + 1, kind="spec", source="xlsx", rows=len(sheet_items)))

    wb.close()
    result.items = items
    result.summary = build_summary(items)
    _fill_metadata(result, pre_header_text, name)
    default_section = _default_section(result.spec_title)
    for summary in result.summary:
        # Явный столбец «Раздел» (если был) — это раздел КП; иначе раздел из заголовка/по умолчанию.
        razdel = next((razdel_by_id[i] for i in summary.item_ids if razdel_by_id.get(i)), "")
        summary.section = razdel or summary.section or default_section
        summary.source_doc = result.doc_code
    for item in items:
        item.source_doc = result.doc_code
    if not result.pages:
        result.warnings.append("в книге не найдено листа со столбцами «Наименование» и «Количество»")
    result.documents = [result.source_summary()]
    return result


def _rows_to_items(
    grid: list[list[object]], filled: set[tuple[int, int]], start: int, mapping: dict[str, int], next_id: int
) -> tuple[list[SpecItem], dict[int, str]]:
    """Позиция начинается со строки с собственным (не унаследованным из объединения) номером
    или количеством. Характеристики берутся из столбца «Технические характеристики» (если он
    есть) и/или из строк-продолжений. Возвращает позиции и {id позиции → раздел из столбца
    «Раздел»} — его в своде используют как раздел КП."""
    items: list[SpecItem] = []
    sections: dict[int, str] = {}
    group = ""  # помещение из строки-заголовка (когда помещение не отдельным столбцом)
    current: SpecItem | None = None
    for r in range(start, len(grid)):
        row = grid[r]
        name = _cell(row, mapping, "name")
        room = _cell(row, mapping, "group")  # столбец «Помещение», если он есть
        razdel = _cell(row, mapping, "razdel")  # столбец «Раздел», если он есть
        own_pos = _own(grid, filled, r, mapping, "pos")
        own_qty = _own(grid, filled, r, mapping, "qty")
        if own_pos or own_qty:  # собственный номер/количество — это новая позиция
            pos = own_pos
            qty_raw = own_qty or _cell(row, mapping, "qty")  # количество может быть общим на группу (объединение)
            specs = _cell(row, mapping, "specs")
            # Строка с одним номером и пустыми наименованием/ед./кол — зарезервированный номер
            # (в перечнях нумерация с пропусками), а не позиция.
            if not name and not specs and not _cell(row, mapping, "type_mark") and not _cell(row, mapping, "unit") and parse_qty(qty_raw) is None:
                current = None
                continue
            current = SpecItem(
                id=next_id + len(items) + 1,
                page=1,
                pos=pos,
                pos_key=normalize_pos(pos),
                description=f"{name} {specs}".strip(),  # наименование + характеристики из своего столбца
                name=short_name(name),
                type_mark=_cell(row, mapping, "type_mark") or _cell(row, mapping, "doc"),
                code=_cell(row, mapping, "code"),
                manufacturer=_cell(row, mapping, "manufacturer"),
                unit=_cell(row, mapping, "unit"),
                qty_raw=qty_raw,
                mass=_cell(row, mapping, "mass"),
                note=_cell(row, mapping, "note"),
                group=room or group,
            )
            current.qty = parse_qty(qty_raw)
            if current.qty is None:
                current.warnings.append(f"не удалось прочитать количество: «{qty_raw}»")
            if not pos:
                current.warnings.append("нет номера позиции")
            elif not POS_OK.match(pos):
                current.warnings.append(f"необычный номер позиции: «{pos}»")
            if not name:
                current.warnings.append("пустое наименование")
            if not current.unit:
                current.warnings.append("нет единицы измерения")
            items.append(current)
            if razdel:
                sections[current.id] = razdel
            continue
        if not name and not room:
            continue
        in_item_merge = (r, mapping["pos"]) in filled or (r, mapping["qty"]) in filled or (mapping.get("unit") is not None and (r, mapping["unit"]) in filled)
        if current is not None and not room and (in_item_merge or not _looks_like_section(name)):
            # Строка внутри вертикального объединения позиции — её характеристика (продолжение
            # описания); то же для непокрытой строки, если она не похожа на заголовок помещения.
            current.description = f"{current.description} {name}".strip()
            extra_mfr = _cell(row, mapping, "manufacturer")
            if extra_mfr and extra_mfr.lower() not in current.manufacturer.lower():
                current.manufacturer = f"{current.manufacturer} {extra_mfr}".strip()
        elif room or _looks_like_section(name):
            group, current = (room or name), None  # заголовок помещения
        else:
            # Оторванная строка без текущей позиции и не похожая на помещение (незамеченная
            # характеристика, хвост заголовка) — помещение ею не портим.
            current = None
    return items, sections


def _fill_metadata(result: ParsedDocument, texts: list[str], file_name: str) -> None:
    joined = " ".join(texts)
    m = DOC_CODE_RE.search(joined)
    result.doc_code = m.group(0) if m else Path(file_name).stem
    m = TITLE_RE.search(joined)
    if m:
        result.title = re.sub(r"\s+", " ", m.group(1)).strip()
    spec = re.search(r"Спецификац[а-я]*[^.]*", joined, re.I)
    if spec:
        result.spec_title = re.sub(r"\s+", " ", spec.group(0)).strip()[:120]
