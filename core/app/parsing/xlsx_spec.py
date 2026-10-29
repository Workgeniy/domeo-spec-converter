"""Разбор спецификации из Excel (xlsx): шапка по словам заголовков, строки — в позиции.

Как и у PDF, столбцы узнаются по словам шапки («Поз.», «Наименование», «Кол-во»…), а не по
их месту: порядок столбцов любой. Нужны минимум «Наименование» и «Количество» (и «Поз.»,
если она есть). Объединённые ячейки разворачиваются (значение из левого верхнего угла
размножается на всю область), строки-заголовки без количества считаются разделом или
помещением — ровно как в PDF.
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path

from openpyxl import load_workbook

from ..models import PageInfo, ParsedDocument, SpecItem
from .aggregate import build_summary
from .spec_parser import DOC_CODE_RE, TITLE_RE, _default_section, normalize_pos, parse_qty, short_name

# Слова-приметы столбца наименования и разбор «товар» vs «работа»: в формах КП (ФПКП) бывают
# ОТДЕЛЬНЫЕ столбцы «Наименование работы» (монтаж/установка) и «Наименование материала» (сам
# товар). Совмещённый «Наименование работ и материалов» — один столбец (есть слово о товаре).
NAME_HINTS = ("наимен", "название", "оборудован", "описан", "номенклат")
GOODS_WORDS = ("материал", "товар", "издел", "продукц", "оборудован", "номенклат")  # столбец о товаре
WORK_WORDS = ("работ", "услуг")  # столбец о работах/услугах — не наименование товара

# Ключ столбца -> слова-приметы в заголовке (подстрока, в нижнем регистре). Порядок проверки
# важен: «Наименование помещения» — это раздел, а не наименование, поэтому раздел ищем раньше.
COLUMN_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("pos", ("поз", "№")),
    ("qty", ("кол", "кол-во", "колво", "колич", "объём", "объем")),  # «Кол»/«Количество»; «Объём»/«Объем» — в формах КП и сметах
    ("unit", ("ед.", "ед ", "единиц", "ед-ц")),
    ("mass", ("масса", "вес")),
    ("code", ("код",)),
    ("manufacturer", ("завод", "изготов", "производ", "поставщик")),
    ("note", ("примеч", "коммент")),
    ("type_mark", ("тип", "марка", "артикул", "модель")),
    ("doc", ("обознач",)),
    ("razdel", ("раздел",)),  # раздел КП («Мебель», «Спортивное оборудование»)
    ("group", ("помещ",)),  # помещение («Групповая комната…»)
    ("name", NAME_HINTS),
    # Характеристики отдельным столбцом («Технические характеристики») — в описание позиции.
    # Ищется после «name», чтобы совмещённый столбец «Наименование и тех. характеристика»
    # достался наименованию, а не характеристикам.
    ("specs", ("техническ", "тех. хар", "характеристик", "параметр")),
]
REQUIRED = ("name", "qty")  # без них лист не считаем спецификацией
HEADER_SCAN_ROWS = 60
MAX_HEADER_COLS = 60  # шире — вряд ли спецификация, не перебираем лишнее
_HAS_LETTER = re.compile(r"[A-Za-zА-Яа-яЁё]")  # наименование товара всегда со словами, не из одних цифр


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
        indices = sorted(range(len(lower)), key=lambda i: 0 if key == "pos" and "поз" in lower[i] else 1)
        for i in indices:
            cell = lower[i]
            if i in used or not cell:
                continue
            if any(h in cell for h in hints):
                mapping[key] = i
                used.add(i)
                break
    if "pos" in mapping and "поз" in lower[mapping["pos"]]:
        for i, label in enumerate(lower):
            if i not in used and re.sub(r"\s+", "", label) in {"№", "№п/п"}:
                mapping["ordinal"] = i  # признак отдельной строки, но не номер позиции в проекте
                break
    # Форма ФПКП: отдельные столбцы «Наименование работы» (монтаж/установка) и «Наименование
    # материала» (товар). Наименование товара — из столбца материала, а не работы; характеристики
    # товара в такой форме лежат в «Примечании» — уводим его в описание, а не в заметку. Если
    # разделения нет (обычная спецификация или совмещённый «…работ и материалов») — ничего не меняем.
    name_like = [i for i, c in enumerate(lower) if c and any(h in c for h in NAME_HINTS)]
    pure_work = [i for i in name_like if any(w in lower[i] for w in WORK_WORDS) and not any(g in lower[i] for g in GOODS_WORDS)]
    goods = [i for i in name_like if any(g in lower[i] for g in GOODS_WORDS)]
    if pure_work and goods:
        mapping["name"] = goods[0]  # «Наименование материала» — тип/категория товара
        used.add(goods[0])
        if "note" in mapping:
            mapping["item"] = mapping.pop("note")  # «Примечание» — сам товар (его подробность)
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


_NOTE_REQUIREMENT = re.compile(r"\b(?:долж(?:ен|но|на|ны)|определя[ею]тся|соответству[ею]т)\b", re.I)


def _item_from_note(raw: object) -> str:
    """Наименование товара из «Примечания» формы ФПКП: первая непустая строка (дальше идут
    требования к изделию/ГОСТ). Если товар и требования в одной строке — режем по началу
    требований («…должен соответствовать»). Длинное — обрезаем по границе слова."""
    line = ""
    for ln in str(raw or "").splitlines():
        s = " ".join(ln.split())
        if s:
            line = s
            break
    cut = len(line)
    m = _NOTE_REQUIREMENT.search(line)
    if m and m.start() >= 8:  # требование — начало характеристик; наименование до него
        cut = min(cut, m.start())
    dot = line.find(". ", 12)  # характеристика часто идёт новым предложением — режем по первой «. »
    if dot != -1:
        cut = min(cut, dot + 1)
    line = line[:cut].rstrip(" .,:;–-")
    if len(line) > 90:
        line = line[:90].rsplit(" ", 1)[0] + "…"
    return line


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
    # При повторной загрузке рабочей выгрузки её свод и детализация — два представления
    # одних товаров. Узнаём их по структуре заголовков, а не по имени файла/проектировщику.
    def header_labels(ws):
        return [{re.sub(r"[^а-яa-z0-9]", "", _text(v).lower()) for v in row}
                for row in ws.iter_rows(max_row=min(ws.max_row, HEADER_SCAN_ROWS), values_only=True)]
    headers = {ws.title: header_labels(ws) for ws in wb.worksheets}
    has_priced_summary = any({"наименование", "колво"} <= labels and
        any(label.startswith("ценазаед") for label in labels)
        for sheet_headers in headers.values() for labels in sheet_headers)
    result = ParsedDocument(file_name=name)
    items: list[SpecItem] = []
    razdel_by_id: dict[int, str] = {}  # id позиции → раздел КП из столбца «Раздел»
    pre_header_text: list[str] = []

    for ws in wb.worksheets:
        if has_priced_summary and any({"документ", "помещениераздел", "замечанияразбора", "стрpdf"} <= labels
                                     for labels in headers[ws.title]):
            result.warnings.append(f"Лист «{ws.title}» пропущен: детализация свода, чтобы не задвоить товары.")
            continue
        grid, filled = _expand_merges(ws)
        found = _find_header(grid)
        if found is None:
            continue
        header_row, mapping = found
        pre_header_text += [_text(v) for row in grid[:header_row] for v in row if _text(v)]
        sheet_items, sheet_sections = _rows_to_items(grid, filled, header_row + 1, mapping, len(items), _row_images(ws))
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


IMAGE_THUMB_PX = 240  # миниатюра товара: хватает и для карточки в приложении, и для вставки в КП
MAX_SHEET_IMAGES = 3000  # защита от аномально тяжёлых книг


def _row_images(ws) -> dict[int, str]:
    """{индекс строки листа (0-based) -> миниатюра товара как data-URI}. Берём первую (самую
    левую) картинку строки — обычно «ИЗОБРАЖЕНИЕ 1». Сбой на одной картинке разбор не роняет."""
    result: dict[int, str] = {}
    images = list(getattr(ws, "_images", []) or [])[:MAX_SHEET_IMAGES]
    for img in sorted(images, key=lambda im: getattr(getattr(im.anchor, "_from", None), "col", 1 << 30)):
        frm = getattr(getattr(img, "anchor", None), "_from", None)
        if frm is None or frm.row in result:
            continue
        thumb = _thumbnail(img)
        if thumb:
            result[frm.row] = thumb
    return result


def _thumbnail(img) -> str:
    try:
        from PIL import Image  # Pillow в зависимостях; при отсутствии — просто без картинок

        im = Image.open(io.BytesIO(img._data()))
        im.thumbnail((IMAGE_THUMB_PX, IMAGE_THUMB_PX))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=75)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 — картинки не критичны для разбора
        return ""


def _rows_to_items(
    grid: list[list[object]], filled: set[tuple[int, int]], start: int, mapping: dict[str, int], next_id: int,
    row_images: dict[int, str] | None = None,
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
        own_ordinal = _own(grid, filled, r, mapping, "ordinal")
        if own_pos or own_qty or own_ordinal:  # порядковый номер сохраняет строки с пропущенными позицией/количеством
            pos = own_pos
            qty_raw = own_qty or _cell(row, mapping, "qty")  # количество может быть общим на группу (объединение)
            specs = _cell(row, mapping, "specs")
            # Наименование и описание. В форме ФПКП товар — в «Примечании» (столбец «item»), а
            # «Наименование материала» (name) — его тип/категория: наименование берём из товара, в
            # описание кладём категорию и полный текст товара. В обычной спеке — наименование + specs.
            if "item" in mapping:
                raw_item = grid[r][mapping["item"]] if mapping["item"] < len(grid[r]) else None
                display_name = _item_from_note(raw_item) or short_name(name)
                description = f"{name} {_text(raw_item)}".strip()
            else:
                display_name = short_name(name)
                description = f"{name} {specs}".strip()
            # Строка-нумерация столбцов под шапкой («1 2 3 … 10») — наименование из одних цифр,
            # не позиция.
            if name and not _HAS_LETTER.search(name):
                current = None
                continue
            # Строка без полезных данных: нет характеристик, марки, единицы и количества.
            empty_payload = (not specs and not _cell(row, mapping, "type_mark")
                             and not _cell(row, mapping, "unit") and parse_qty(qty_raw) is None)
            # Такую строку пропускаем, если это либо голый номер без наименования
            # (зарезервированный номер / служебная строка выгрузки), либо заголовок раздела,
            # пронумерованный как позиция, но не порядковым номером (в перечнях, формах КП и
            # сметах так нумеруют разделы). Строку с порядковым номером (own_ordinal) не теряем.
            if empty_payload and (not name or (own_pos and not own_ordinal)):
                current = None
                continue
            current = SpecItem(
                id=next_id + len(items) + 1,
                page=1,
                pos=pos,
                pos_key=normalize_pos(pos),
                description=description,  # наименование + характеристики (в ФПКП — категория + товар)
                name=display_name,
                type_mark=_cell(row, mapping, "type_mark") or _cell(row, mapping, "doc"),
                code=_cell(row, mapping, "code"),
                manufacturer=_cell(row, mapping, "manufacturer"),
                unit=_cell(row, mapping, "unit"),
                qty_raw=qty_raw,
                mass=_cell(row, mapping, "mass"),
                note=_cell(row, mapping, "note"),
                group=room or group,
                image=(row_images or {}).get(r, ""),  # встроенная картинка товара из этой строки
            )
            current.qty = parse_qty(qty_raw)
            if current.qty is None:
                current.warnings.append(f"не удалось прочитать количество: «{qty_raw}»")
            if not pos:
                current.warnings.append("нет номера позиции")
            elif not POS_OK.match(pos):
                current.warnings.append(f"необычный номер позиции: «{pos}»")
            if not display_name:
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
            if not current.image and row_images and row_images.get(r):  # картинка на строке-продолжении
                current.image = row_images[r]
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
