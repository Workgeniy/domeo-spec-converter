"""HTTP API: разбор PDF со спецификацией и выгрузка в Excel."""

from __future__ import annotations

import io
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .export.excel import build_workbook
from .models import ExportRequest, ParsedDocument
from .parsing.ocr import default_provider
from .parsing.spec_parser import parse_pdf

MAX_UPLOAD_BYTES = 100 * 1024 * 1024

app = FastAPI(title="Domeo Spec Converter", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.get("/api/health")
def health() -> dict:
    ocr = default_provider()
    return {"status": "ok", "ocr": ocr.name if ocr else None}


@app.post("/api/parse", response_model=ParsedDocument)
async def parse(file: UploadFile = File(...)) -> ParsedDocument:
    name = file.filename or "документ.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Ожидается файл PDF")
    content = await file.read()
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


# Собранный фронтенд (web/dist) раздаётся тем же процессом, если он есть.
_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
