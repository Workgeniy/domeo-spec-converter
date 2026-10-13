"""HTTP API ядра разбора: PDF со спецификацией -> JSON, JSON -> Excel.

Это внутренний сервис: наружу его закрывает ASP.NET Core API (api/), который и
разговаривает с фронтом. Поэтому здесь нет CORS, авторизации и раздачи статики.
"""

from __future__ import annotations

import io
import re
from threading import Lock
from pathlib import Path
from urllib.parse import quote

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse

from .env import load_env_file
from .export.excel import build_workbook
from .models import (
    ExportRequest,
    IndexationInfo,
    IndexationRates,
    InternetLookupRequest,
    InternetLookupResponse,
    InternetSearchInfo,
    MatchRequest,
    MatchResponse,
    ParsedDocument,
    PriceListInfo,
    Supplier,
    SupplierCreate,
    SupplierIndexInfo,
    SupplierSample,
    SupplierSettings,
    SupplierUpdate,
)
from .parsing.ocr import default_provider
from .parsing.document import is_supported, parse_document
from .parsing.drawing import drawing_text
from .pricing.indexation import IndexationStore, history_indexation
from .pricing.internet import InternetPriceService
from .pricing.store import PriceListStore
from .pricing.suppliers.discovery import WebPriceSearch
from .pricing.suppliers.index import SupplierIndex
from .pricing.websearch import engine_from_env

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_INTERNET_ITEMS = 50  # поиск — долгий (десятки секунд на позицию), фронт шлёт пачками
MAX_DRAWING_BYTES = 25 * 1024 * 1024
drawing_lock = Lock()

load_env_file()  # ключи для локального запуска — из core/.env, если он есть
price_lists = PriceListStore()
indexation_rates = IndexationStore()
supplier_index = SupplierIndex()
search_engine = engine_from_env()
web_search = WebPriceSearch(search_engine, supplier_index) if search_engine is not None else None
supplier_index.search_engine = search_engine.name if search_engine is not None else ""
internet_prices = InternetPriceService.from_env(supplier_index, web_search, price_lists.market_names)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Прайс закупки, индекс поставщиков и кэши, накопленные раньше, подхватываются при старте.
    price_lists.load()
    indexation_rates.load()
    supplier_index.load()
    if web_search is not None:
        web_search.load()
    internet_prices.load()
    yield


app = FastAPI(title="Domeo Spec Converter — ядро разбора", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    ocr = default_provider()
    return {
        "status": "ok",
        "ocr": ocr.name if ocr else None,
        "pricelist": price_lists.price_list is not None,
        "internet": internet_prices.configured,
        "suppliers": len(supplier_index.suppliers),
    }


# ---------- каталоги поставщиков ----------


def _supplier_or_404(supplier_id: str) -> Supplier:
    try:
        return supplier_index.get(supplier_id)
    except KeyError:
        raise HTTPException(404, "Поставщик не найден") from None


@app.get("/api/suppliers", response_model=SupplierIndexInfo)
def suppliers_info() -> SupplierIndexInfo:
    return supplier_index.info()


@app.put("/api/suppliers/settings", response_model=SupplierIndexInfo)
def suppliers_settings(body: SupplierSettings) -> SupplierIndexInfo:
    """Глубина обхода найденных автопоиском сайтов (0 — не обходить) и сколько магазинов по
    позиции считать достаточным, чтобы не ходить в интернет."""
    return supplier_index.set_settings(body.autocrawl_pages, body.min_shops)


@app.post("/api/suppliers", response_model=Supplier)
def suppliers_add(body: SupplierCreate) -> Supplier:
    try:
        return supplier_index.add(body.name, body.site, body.max_pages, body.sections)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/suppliers/{supplier_id}", response_model=Supplier)
def suppliers_update(supplier_id: str, body: SupplierUpdate) -> Supplier:
    """Название, разделы и глубина обхода поставщика."""
    _supplier_or_404(supplier_id)
    return supplier_index.update(supplier_id, body.name, body.sections, body.max_pages)


# ---------- индексация цен к дате поставки ----------


@app.get("/api/indexation", response_model=IndexationInfo)
def indexation_info() -> IndexationInfo:
    """Рост цен по истории закупок (если она загружена) и ставки, выбранные оператором."""
    history = history_indexation(price_lists.price_list) if price_lists.price_list is not None else None
    return IndexationInfo(history=history, rates=indexation_rates.list())


@app.put("/api/indexation", response_model=IndexationInfo)
def indexation_set(body: IndexationRates) -> IndexationInfo:
    """Справочник ставок по разделам заменяется целиком."""
    indexation_rates.set_rates(body.rates)
    return indexation_info()


@app.delete("/api/suppliers/{supplier_id}", status_code=204)
def suppliers_remove(supplier_id: str) -> Response:
    try:
        supplier_index.remove(supplier_id)
    except KeyError:
        raise HTTPException(404, "Поставщик не найден") from None
    return Response(status_code=204)


@app.post("/api/suppliers/{supplier_id}/crawl", response_model=Supplier)
def suppliers_crawl(supplier_id: str) -> Supplier:
    """Запустить обход сайта поставщика в фоне; состояние — в GET /api/suppliers."""
    _supplier_or_404(supplier_id)
    try:
        return supplier_index.start_crawl(supplier_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/suppliers/{supplier_id}/stop", response_model=Supplier)
def suppliers_stop(supplier_id: str) -> Supplier:
    supplier = _supplier_or_404(supplier_id)
    supplier_index.stop_crawl(supplier_id)
    return supplier


@app.post("/api/suppliers/{supplier_id}/pricelist", response_model=Supplier)
def suppliers_pricelist(supplier_id: str, file: UploadFile = File(...), file_name: str | None = Form(None), section: str | None = Form(None)) -> Supplier:
    """Прайс-лист поставщика (xlsx). С разделом заменяет цены только этого раздела, без — все."""
    _supplier_or_404(supplier_id)
    name = file_name or file.filename or "прайс.xlsx"
    if not name.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Ожидается прайс-лист в формате xlsx")
    content = file.file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Файл больше 100 МБ")
    try:
        return supplier_index.import_price_list(supplier_id, content, name, section or "")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Не удалось прочитать прайс: {exc}") from exc


@app.get("/api/suppliers/{supplier_id}/sample", response_model=SupplierSample)
def suppliers_sample(supplier_id: str) -> SupplierSample:
    _supplier_or_404(supplier_id)
    return SupplierSample(offers=supplier_index.sample(supplier_id))


# ---------- прайс закупки ----------


@app.get("/api/pricelist", response_model=PriceListInfo)
def pricelist_info() -> PriceListInfo:
    info = price_lists.info()
    if info is None:
        raise HTTPException(404, "Прайс закупки ещё не загружен")
    return info


@app.post("/api/pricelist", response_model=PriceListInfo)
def pricelist_upload(file: UploadFile = File(...), file_name: str | None = Form(None)) -> PriceListInfo:
    """Выгрузка 1С «Заказы поставщикам» (xlsx) → прайс закупки. Заменяет прежний прайс."""
    name = file_name or file.filename or "история.xlsx"
    if not name.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Ожидается выгрузка 1С в формате xlsx")
    content = file.file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Файл больше 100 МБ")
    try:
        return price_lists.build_from_upload(content, name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Не удалось прочитать выгрузку: {exc}") from exc


@app.post("/api/pricelist/match", response_model=MatchResponse)
def pricelist_match(request: MatchRequest) -> MatchResponse:
    if price_lists.matcher is None:
        raise HTTPException(409, "Прайс закупки ещё не загружен")
    return MatchResponse(matches=price_lists.match(request.items))


# ---------- цена из интернета ----------


@app.get("/api/internet", response_model=InternetSearchInfo)
def internet_info() -> InternetSearchInfo:
    return internet_prices.info()


@app.post("/api/internet/lookup", response_model=InternetLookupResponse)
def internet_lookup(request: InternetLookupRequest) -> InternetLookupResponse:
    """Поиск цен на дату для пачки позиций. Синхронный обработчик: ждём модель в пуле потоков."""
    if not internet_prices.configured:
        raise HTTPException(409, "Поиск цен в интернете не настроен: на сервере нет ключа ANTHROPIC_API_KEY")
    if len(request.items) > MAX_INTERNET_ITEMS:
        raise HTTPException(400, f"За один запрос ищем не больше {MAX_INTERNET_ITEMS} позиций")
    return InternetLookupResponse(lookups=internet_prices.lookup_many(request.items, refresh=request.refresh))


@app.post("/api/parse", response_model=ParsedDocument)
def parse(file: UploadFile = File(...), file_name: str | None = Form(None)) -> ParsedDocument:
    # Обработчик синхронный намеренно: разбор — тяжёлая CPU-работа, и в async-обработчике он
    # заблокировал бы цикл событий (health и второй разбор ждали бы). Так FastAPI уводит
    # его в пул потоков.
    # Имя файла в заголовке multipart у некоторых клиентов (в т. ч. .NET) теряет кириллицу,
    # поэтому настоящее имя можно передать отдельным полем формы.
    name = file_name or file.filename or "документ.pdf"
    if not is_supported(name):
        raise HTTPException(400, "Ожидается файл PDF или Excel (xlsx)")
    content = file.file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Файл больше 100 МБ")
    try:
        return parse_document(content, file_name=name)
    except Exception as exc:  # noqa: BLE001 — любая ошибка разбора отдаётся клиенту текстом
        raise HTTPException(422, f"Не удалось разобрать файл: {exc}") from exc


@app.post("/api/drawing-text")
def extract_drawing_text(file: UploadFile = File(...), pages: str = Form(...)) -> dict:
    # Ограничение объёма и числа страниц: обрабатываем последовательно, без растра и моделей.
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "План нужен в формате PDF.")
    if not drawing_lock.acquire(blocking=False):
        raise HTTPException(503, "Другая сверка плана уже выполняется. Повторите после её завершения.")
    try:
        content = file.file.read(MAX_DRAWING_BYTES + 1)
        if len(content) > MAX_DRAWING_BYTES:
            raise HTTPException(413, "Для сверки выберите PDF до 25 МБ или отдельный файл с нужными планами.")
        selected = [int(value.strip()) for value in pages.split(",") if value.strip()]
        return drawing_text(content, selected)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"Не удалось прочитать план: {exc}") from exc
    finally:
        drawing_lock.release()


@app.post("/api/export")
def export(data: ExportRequest) -> StreamingResponse:
    try:
        wb = build_workbook(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    stem = re.sub(r"[\\/:*?\"<>|]+", "_", Path(data.file_name).stem) or "спецификация"
    filename = f"{stem}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
