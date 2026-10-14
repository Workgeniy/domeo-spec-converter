<#
Сборка автономного десктоп-дистрибутива Domeo (Windows x64) — один бандл build/bundle.
Требуется: .NET 9 SDK; Python 3.12 с зависимостями ядра и PyInstaller
(pip install -r core/requirements.txt pyinstaller); бинарники PostgreSQL 15; node/npm для фронта.
OCR — опционально: передать путь к установщику tesseract (UB-Mannheim).

Пример:
  powershell -ExecutionPolicy Bypass -File desktop\build.ps1 -Zip `
     -TesseractSetup "$env:USERPROFILE\Downloads\tesseract-ocr-w64-setup-5.4.0.20240606.exe"
#>
param(
  [string]$PgSource = "C:\Program Files\PostgreSQL\15",
  [string]$TesseractSetup = "",
  [switch]$Zip
)
$ErrorActionPreference = "Stop"
$desktop = $PSScriptRoot
$repo = Split-Path -Parent $desktop
$build = Join-Path $desktop "build"
$dist = Join-Path $build "dist"
$bundle = Join-Path $build "bundle"

function Say($m) { Write-Host "== $m" -ForegroundColor Cyan }

Say "Ядро (PyInstaller)"
Push-Location (Join-Path $repo "core")
python -m PyInstaller --noconfirm --clean --name domeo-spec-core `
  --distpath $dist --workpath (Join-Path $build "work") --specpath $build `
  --collect-submodules app --collect-submodules uvicorn --collect-submodules ddgs `
  --collect-submodules multipart --collect-submodules anthropic `
  --collect-all fitz --collect-all pydantic --collect-all pydantic_core --collect-all snowballstemmer `
  --exclude-module torch --exclude-module tensorflow --exclude-module tensorboard `
  --exclude-module matplotlib --exclude-module pandas --exclude-module scipy --exclude-module transformers `
  run_core.py
Pop-Location

Say "Фронт (npm run build)"
Push-Location (Join-Path $repo "web"); npm run build; Pop-Location

Say "API (self-contained)"
dotnet publish (Join-Path $repo "api\src\DomeoSpec.Api\DomeoSpec.Api.csproj") -c Release -r win-x64 --self-contained true -o (Join-Path $dist "api")

Say "Оболочка (self-contained) -> bundle"
if (Test-Path $bundle) { Remove-Item $bundle -Recurse -Force }
dotnet publish (Join-Path $desktop "DomeoSpec.Desktop\DomeoSpec.Desktop.csproj") -c Release -r win-x64 --self-contained true -p:PublishSingleFile=false -o $bundle

Say "Сборка бандла"
Copy-Item (Join-Path $dist "domeo-spec-core") (Join-Path $bundle "core") -Recurse -Force
Copy-Item (Join-Path $repo "web\dist") (Join-Path $bundle "web") -Recurse -Force
Copy-Item (Join-Path $dist "api") (Join-Path $bundle "api") -Recurse -Force
foreach ($sub in "bin","lib","share") {
  robocopy (Join-Path $PgSource $sub) (Join-Path $bundle "pgsql\$sub") /E /NFL /NDL /NJH /NJS /R:1 /W:1 | Out-Null
}
Copy-Item (Join-Path $desktop "INSTALL.txt") (Join-Path $bundle "Как установить.txt") -Force  # памятка для пользователя

if ($TesseractSetup -and (Test-Path $TesseractSetup)) {
  Say "OCR (tesseract)"
  $tdir = Join-Path $build "tesseract-install"
  if (Test-Path $tdir) { Remove-Item $tdir -Recurse -Force }
  Start-Process -FilePath $TesseractSetup -ArgumentList "/S", "/D=$tdir" -Wait
  $tb = Join-Path $bundle "tesseract"
  New-Item -ItemType Directory -Force -Path (Join-Path $tb "tessdata") | Out-Null
  Get-ChildItem (Join-Path $tdir "*.exe"), (Join-Path $tdir "*.dll") -ErrorAction SilentlyContinue | Copy-Item -Destination $tb -Force
  foreach ($lng in "rus", "eng", "osd") {
    $f = Join-Path $tdir "tessdata\$lng.traineddata"
    if (Test-Path $f) { Copy-Item $f (Join-Path $tb "tessdata") -Force }
  }
}

Say "Готово: $bundle"
if ($Zip) {
  $zip = Join-Path $build "Domeo-portable.zip"
  if (Test-Path $zip) { Remove-Item $zip -Force }
  Compress-Archive -Path "$bundle\*" -DestinationPath $zip
  Say "ZIP: $zip"
}
