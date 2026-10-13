# Desktop — автономное Windows-приложение

Оболочка `DomeoSpec.Desktop` (WinForms + WebView2) превращает веб-приложение в десктоп:
нативное окно показывает интерфейс, а бэкенд (ядро разбора + API + база) поднимается на
localhost как дочерние процессы. В автономной сборке рядом с `Domeo.exe` лежат все части —
Python, .NET и PostgreSQL ставить не нужно.

## Как это устроено
`Backend.cs` при запуске:
1. если есть `pgsql/bin/pg_ctl.exe` — поднимает портативный **PostgreSQL** (кластер в
   `%LOCALAPPDATA%\DomeoSpec\pgdata`, init при первом старте, trust только на localhost) и
   отдаёт строку подключения в API (разделы «История КП» и «Объекты»);
2. запускает **ядро** (`core/domeo-spec-core.exe`, PyInstaller; в разработке — `python -m uvicorn`);
3. запускает **API** (`api/DomeoSpec.Api.exe`, self-contained; в разработке — собранный DLL),
   передаёт ему `Engine__BaseUrl`, `Web__DistPath` (папка `web/`), строку БД;
4. ждёт `/api/specifications/health` и открывает интерфейс в WebView2.

При закрытии окна дочерние процессы и кластер PostgreSQL останавливаются.
Данные приложения (кэш цен, индекс поставщиков, БД) — в `%LOCALAPPDATA%\DomeoSpec`, отдельно
от самой программы.

## Состав автономного бандла (`build/bundle/`)
```
Domeo.exe + рантайм .NET      — оболочка (self-contained WinForms)
core/   domeo-spec-core.exe   — ядро разбора (PyInstaller): PDF/xlsx, картинки, цены
api/    DomeoSpec.Api.exe      — API (self-contained ASP.NET Core)
web/    index.html + assets    — собранный фронт
pgsql/  bin/ lib/ share/       — портативный PostgreSQL 15
tesseract/ tesseract.exe + tessdata (rus, eng) — OCR сканов (опционально)
```

## Сборка (на машине с .NET 9 SDK, Python 3.12 + зависимости ядра, PyInstaller)
Автоматически: `powershell desktop/build.ps1` (см. параметры внутри). Вручную — шаги:

1. **Ядро → exe** (из `core/`):
   ```
   python -m PyInstaller --noconfirm --clean --name domeo-spec-core \
     --distpath ../desktop/build/dist --workpath ../desktop/build/work --specpath ../desktop/build \
     --collect-submodules app --collect-submodules uvicorn --collect-submodules ddgs \
     --collect-submodules multipart --collect-submodules anthropic \
     --collect-all fitz --collect-all pydantic --collect-all pydantic_core --collect-all snowballstemmer \
     --exclude-module torch --exclude-module tensorflow --exclude-module matplotlib \
     --exclude-module pandas --exclude-module scipy run_core.py
   ```
   (`torch` и прочее тяжёлое исключаем — ядру не нужны, иначе сборка раздувается.)
2. **Фронт**: `cd web && npm run build` → копируем `web/dist` в `build/bundle/web`.
3. **API self-contained**:
   `dotnet publish api/src/DomeoSpec.Api/DomeoSpec.Api.csproj -c Release -r win-x64 --self-contained true -o build/bundle/api`
4. **Оболочка self-contained**:
   `dotnet publish desktop/DomeoSpec.Desktop -c Release -r win-x64 --self-contained true -o build/bundle`
5. Копируем `domeo-spec-core/` → `build/bundle/core`, `pgsql/` (из установленного PostgreSQL 15
   или портативного) → `build/bundle/pgsql`.
6. **OCR**: из установщика tesseract (UB-Mannheim) копируем `tesseract.exe` + нужные DLL +
   `tessdata/{rus,eng,osd}.traineddata` в `build/bundle/tesseract`.
7. **Установщик**: `ISCC desktop/installer.iss` (Inno Setup) → один `.exe`-установщик; либо
   раздавать `build/bundle` как папку/ZIP (тоже автономно).

## Важно: путь установки без кириллицы
Встроенный **PostgreSQL на Windows не работает из пути с не-ASCII символами** (кириллица в
названии папки → `FATAL: invalid byte sequence for encoding "UTF8"`). Поэтому ставить/распаковывать
приложение нужно в путь из латиницы — по умолчанию установщик ставит в `C:\Program Files\Domeo`
(ок). Ядро разбора и tesseract кириллический путь переносят, Postgres — нет. Данные БД всегда в
`%LOCALAPPDATA%\DomeoSpec` (ASCII при обычном имени пользователя).

## Запуск в разработке
`dotnet run --project desktop/DomeoSpec.Desktop` — оболочка найдёт репозиторий и поднимет
ядро через `python -m uvicorn`, API — через собранный DLL, фронт — из `web/dist` (нужен
`npm run build`). Без `pgsql/` рядом история/объекты отключены — основной поток работает.
