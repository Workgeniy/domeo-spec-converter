"""HTTP API ядра разбора: PDF со спецификацией -> JSON, JSON -> Excel.

Это внутренний сервис: наружу его закрывает ASP.NET Core API (api/), который и
разговаривает с фронтом. Поэтому здесь нет CORS, авторизации и раздачи статики.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from urllib.parse import quote

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .env import load_env_file
from .export.excel import build_workbook
from .models import (
    ExportRequest,
    InternetLookupRequest,
    InternetLookupResponse,
    InternetSearchInfo,
    MatchRequest,
    MatchResponse,
    ParsedDocument,
    PriceListInfo,
)
from .parsing.ocr import default_provider
from .parsing.spec_parser import parse_pdf
from .pricing.internet import InternetPriceService
from .pricing.store import PriceListStore

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_INTERNET_ITEMS = 50  # поиск — долгий (десятки секунд на позицию), фронт шлёт пачками

load_env_file()  # ключи для локального запуска — из core/.env, если он есть
price_lists = PriceListStore()
internet_prices = InternetPriceService.from_env()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Прайс закупки и кэш интернет-цен, накопленные раньше, подхватываются при старте.
    price_lists.load()
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
    }


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
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Ожидается файл PDF")
    content = file.file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Файл больше 100 МБ")
    try:
        return parse_pdf(content, file_name=name)
    except Exception as exc:  # noqa: BLE001 — любая ошибка разбора отдаётся клиенту текстом
        raise HTTPException(422, f"Не удалось разобрать PDF: {exc}") from exc


@app.post("/api/export")
def export(data: ExportRequest) -> StreamingResponse:
    wb = build_workbook(data)
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
