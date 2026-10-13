"""Точка входа автономного ядра (PyInstaller): поднимает FastAPI-приложение на нужном порту.

Запуск в десктоп-сборке: domeo-spec-core.exe --port 8600
DATA_DIR (кэш цен, индекс поставщиков) берётся из окружения, задаёт десктоп-оболочка.
"""

from __future__ import annotations

import argparse

import uvicorn

from app.main import app


def main() -> None:
    parser = argparse.ArgumentParser(description="Ядро разбора Domeo")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
