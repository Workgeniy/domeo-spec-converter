# Ядро разбора: Python + PyMuPDF + Tesseract (русский) для сканов.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Tesseract с русским пакетом — чтобы страницы-сканы распознавались прямо в контейнере.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app

# Не root: сервису не нужны права на запись в образ. Единственное, что он пишет, —
# прайс закупки в /data (том; владельца каталога Docker переносит на новый том).
RUN useradd --system --uid 10001 --no-create-home app \
    && mkdir -p /data && chown app:app /data
ENV DATA_DIR=/data
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

# Один воркер: разбор PDF — тяжёлая CPU-работа, sync-обработчик и так уходит в пул потоков;
# второй воркер на ВМ с 4 ГБ памяти только удвоил бы потребление.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
