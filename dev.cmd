@echo off
chcp 65001 >nul
rem Запуск всех трёх частей для разработки, каждая в своём окне:
rem   ядро разбора (Python)  -> http://localhost:8000
rem   API (ASP.NET Core)     -> http://localhost:5080  (Swagger: /swagger)
rem   фронт (Vite)           -> http://localhost:5180  <- открывать это
rem Остановить: закрыть окна или Ctrl+C в каждом.

set ROOT=%~dp0

start "spec-core :8000" cmd /k "cd /d "%ROOT%core" && python -m uvicorn app.main:app --reload --port 8000"
start "spec-api :5080" cmd /k "cd /d "%ROOT%api" && "C:\Program Files\dotnet\dotnet.exe" run --project src\DomeoSpec.Api --no-launch-profile --urls http://localhost:5080"
start "spec-web :5180" cmd /k "cd /d "%ROOT%web" && npm run dev"

echo Подождите 10-20 секунд, пока поднимется API, и откройте http://localhost:5180
timeout /t 15 >nul
start http://localhost:5180
