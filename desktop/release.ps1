<#
Выпуск новой версии Domeo с авто-обновлением (Velopack + GitHub Releases).

Пересобирает .NET-оболочку, пакует Velopack-релиз (с дельтой от прошлой версии — качается у
пользователя быстро) и публикует его на GitHub. Установленные у пользователей Domeo подхватят
обновление при следующем запуске.

Ядро/фронт/API берутся из уже собранного бандла desktop/build/bundle. Если менялись ИМЕННО они
(а не только оболочка) — сначала полная пересборка бандла:  powershell -File desktop\build.ps1

  powershell -ExecutionPolicy Bypass -File desktop\release.ps1 -Version 1.0.1

Требуется: .NET 9 SDK; vpk (dotnet tool install -g vpk); gh (авторизован: gh auth login).
#>
param([Parameter(Mandatory = $true)][string]$Version)
$ErrorActionPreference = "Stop"
$desktop = $PSScriptRoot
$bundle = Join-Path $desktop "build\bundle"
$rel = Join-Path $desktop "build\Releases"
$shell = Join-Path $desktop "build\shell"
$csproj = Join-Path $desktop "DomeoSpec.Desktop\DomeoSpec.Desktop.csproj"
$dotnet = "C:\Program Files\dotnet\dotnet.exe"
$vpk = Join-Path $env:USERPROFILE ".dotnet\tools\vpk.exe"
$repoUrl = "https://github.com/Workgeniy/domeo-spec-converter"

if (-not (Test-Path (Join-Path $bundle "core\domeo-spec-core.exe"))) {
  throw "Бандл не найден: $bundle. Сначала собери его: desktop\build.ps1"
}

Write-Host "== 1/4 Оболочка (.NET publish $Version)" -ForegroundColor Cyan
if (Test-Path $shell) { Remove-Item $shell -Recurse -Force }
& $dotnet publish $csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=false -p:Version=$Version -o $shell
if ($LASTEXITCODE -ne 0) { throw "dotnet publish завершился с ошибкой" }
# Оболочка + Velopack.dll -> в бандл (ядро/web/api/pgsql не трогаем).
robocopy $shell $bundle /E /NFL /NDL /NJH /NJS /R:1 /W:1 | Out-Null

Write-Host "== 2/4 Прошлый релиз из GitHub (для дельты)" -ForegroundColor Cyan
if (Test-Path $rel) { Remove-Item $rel -Recurse -Force }
New-Item -ItemType Directory -Force -Path $rel | Out-Null
# Скачает последнюю опубликованную версию, чтобы pack сделал дельту. Первый релиз — скачивать
# нечего, это нормально.
& $vpk download github --repoUrl $repoUrl --outputDir $rel

Write-Host "== 3/4 Упаковка Velopack $Version" -ForegroundColor Cyan
& $vpk pack --packId Domeo --packVersion $Version --packDir $bundle --mainExe Domeo.exe --outputDir $rel --packTitle "Domeo" --packAuthors "Domeo" --runtime win-x64
if ($LASTEXITCODE -ne 0) { throw "vpk pack завершился с ошибкой" }

Write-Host "== 4/4 Публикация на GitHub Releases" -ForegroundColor Cyan
$tok = (gh auth token).Trim()
if (-not $tok) { throw "gh не авторизован — выполни: gh auth login" }
& $vpk upload github --repoUrl $repoUrl --token $tok --publish --releaseName "Domeo $Version" --tag "v$Version" --outputDir $rel
if ($LASTEXITCODE -ne 0) { throw "vpk upload завершился с ошибкой" }

Write-Host ""
Write-Host "Готово: v$Version опубликован. Установленные Domeo обновятся при следующем запуске." -ForegroundColor Green
Write-Host "Setup для новых пользователей: $repoUrl/releases/latest" -ForegroundColor Green
