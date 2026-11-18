# Builds dist\ezClipping.exe: the app and ffmpeg in one file, plus ffmpeg's license and the README next to it.
# Needs: .venv with requirements.txt + requirements-dev.txt, and ffmpeg on PATH (e.g. winget install Gyan.FFmpeg.Essentials).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ffmpeg = (Get-Command ffmpeg).Source
New-Item -ItemType Directory -Force vendor | Out-Null
Copy-Item $ffmpeg vendor\ffmpeg.exe
Copy-Item (Join-Path (Split-Path (Split-Path $ffmpeg)) "LICENSE") vendor\FFMPEG-LICENSE.txt  # GPL: ship it with the exe
.venv\Scripts\python -c "from ezclipping.__main__ import tray_image; tray_image(True).save('vendor/ezclipping.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])"

$ErrorActionPreference = "Continue"  # PowerShell 5.1 would treat PyInstaller's warnings on stderr as fatal
.venv\Scripts\pyinstaller --noconfirm --clean --log-level WARN --onefile --noconsole --name ezClipping `
    --icon vendor\ezclipping.ico --paths . --add-binary "vendor\ffmpeg.exe;." ezclipping\__main__.py 2>&1 | Write-Host
if ($LASTEXITCODE) { throw "PyInstaller failed" }
$ErrorActionPreference = "Stop"

Copy-Item vendor\FFMPEG-LICENSE.txt, README.md dist\
Get-ChildItem dist | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
