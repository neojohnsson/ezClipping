# Builds dist\ezClipping.exe (the app and ffmpeg in one file) and the release zip with licenses and SHA-256 sums.
# Needs: .venv with requirements.txt + requirements-dev.txt, and the pinned ffmpeg on PATH
# (winget install Gyan.FFmpeg.Essentials, version 8.0).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# The exact ffmpeg THIRD-PARTY-NOTICES.md describes. Changing ffmpeg is a deliberate step: update both.
$FFMPEG_SHA256 = "1FCB0CB525085CC5BE3AD4BE16799D60786B65CC36951622A018D00F78C0FB5D"  # 8.0 essentials, gyan.dev
$ffmpeg = (Get-Command ffmpeg).Source
if ((Get-FileHash $ffmpeg -Algorithm SHA256).Hash -ne $FFMPEG_SHA256) {
    throw "ffmpeg on PATH ($ffmpeg) isn't the pinned build. Update FFMPEG_SHA256 and THIRD-PARTY-NOTICES.md on purpose."
}
New-Item -ItemType Directory -Force vendor | Out-Null
Copy-Item $ffmpeg vendor\ffmpeg.exe
Copy-Item (Join-Path (Split-Path (Split-Path $ffmpeg)) "LICENSE") vendor\FFMPEG-LICENSE.txt  # GPL: ship it with the exe
.venv\Scripts\python -c "from ezclipping.__main__ import tray_image; tray_image(True).save('vendor/ezclipping.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])"

$ErrorActionPreference = "Continue"  # PowerShell 5.1 would treat PyInstaller's warnings on stderr as fatal
.venv\Scripts\pyinstaller --noconfirm --clean --log-level WARN --onefile --noconsole --name ezClipping `
    --icon vendor\ezclipping.ico --paths . --add-binary "vendor\ffmpeg.exe;." ezclipping\__main__.py 2>&1 | Write-Host
if ($LASTEXITCODE) { throw "PyInstaller failed" }
$ErrorActionPreference = "Stop"

$version = .venv\Scripts\python -c "import ezclipping; print(ezclipping.__version__)"
$files = "LICENSE", "THIRD-PARTY-NOTICES.md", "README.md", "vendor\FFMPEG-LICENSE.txt"
Copy-Item $files dist\
$zip = "dist\ezClipping-$version.zip"
Compress-Archive -Force -DestinationPath $zip -Path dist\ezClipping.exe, dist\LICENSE, dist\THIRD-PARTY-NOTICES.md, `
    dist\README.md, dist\FFMPEG-LICENSE.txt
Get-FileHash dist\ezClipping.exe, $zip -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash.ToLower())  $(Split-Path $_.Path -Leaf)" } | Set-Content -Encoding ascii dist\SHA256SUMS.txt
Get-ChildItem dist | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
Get-Content dist\SHA256SUMS.txt
