"""Переменные окружения из файла ``core/.env`` для локального запуска.

На стенде ключи приходят из окружения контейнера (deploy/secrets.env), а разработчику
удобнее положить ``ANTHROPIC_API_KEY=...`` в ``core/.env`` (в git не попадает). Уже
заданные переменные окружения файл не перекрывает.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_env_file(path: str | Path | None = None) -> dict[str, str]:
    file = Path(path or DEFAULT_ENV_FILE)
    loaded: dict[str, str] = {}
    if not file.exists():
        return loaded
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded
