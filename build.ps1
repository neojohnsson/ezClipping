# Builds dist\ezClipping.exe and the release zip (exe, licenses, README, SHA-256 sums).
# Needs: .venv with requirements.txt + requirements-dev.txt. ffmpeg is NOT bundled: users install it themselves.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force vendor | Out-Null
.venv\Scripts\python -c "from ezclipping.__main__ import tray_image; tray_image(True).save('vendor/ezclipping.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])"
if ($LASTEXITCODE) { throw "Couldn't make the icon" }  # "Stop" doesn't cover programs' exit codes in PS 5.1

# Only Windows and this Python on PATH: PyInstaller copies DLLs it finds on PATH (it took a JDK's otherwise)
$python = .venv\Scripts\python -c "import sys; print(sys.base_prefix)"
$savedPath = $env:PATH
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$python;$python\DLLs;$PSScriptRoot\.venv\Scripts"
$ErrorActionPreference = "Continue"  # PowerShell 5.1 would treat PyInstaller's warnings on stderr as fatal
.venv\Scripts\pyinstaller --noconfirm --clean --log-level WARN --onefile --noconsole --name ezClipping `
    --icon vendor\ezclipping.ico --paths . ezclipping\__main__.py 2>&1 | Write-Host
$failed = $LASTEXITCODE
$ErrorActionPreference = "Stop"
$env:PATH = $savedPath
if ($failed) { throw "PyInstaller failed" }

# License texts of everything inside the exe (CPython's covers OpenSSL, libffi, Tcl/Tk, zlib, bzip2, xz)
Remove-Item -Recurse -Force dist\licenses -ErrorAction SilentlyContinue
@'
import importlib.metadata as md, pathlib, shutil, sys
out = pathlib.Path("dist/licenses")
out.mkdir(parents=True)
for name in ["obsws-python", "pystray", "pillow", "websocket-client", "six", "pyinstaller"]:
    dist = md.distribution(name)
    for f in dist.files:
        if any(word in f.name.upper() for word in ("LICENSE", "COPYING", "NOTICE")):
            stem = f.name[:-4] if f.name.lower().endswith(".txt") else f.name
            shutil.copy(dist.locate_file(f), out / f"{name}-{stem}.txt")
shutil.copy(pathlib.Path(sys.base_prefix) / "LICENSE.txt", out / "python-LICENSE.txt")
print("\n".join(sorted(p.name for p in out.iterdir())))
'@ | .venv\Scripts\python -
if ($LASTEXITCODE) { throw "Couldn't collect the license texts" }

$version = .venv\Scripts\python -c "import ezclipping; print(ezclipping.__version__)"
if ($LASTEXITCODE -or -not $version) { throw "Couldn't read the version" }
Copy-Item LICENSE, THIRD-PARTY-NOTICES.md, README.md dist\
Remove-Item dist\FFMPEG-LICENSE.txt -ErrorAction SilentlyContinue  # from older builds that bundled ffmpeg
$zip = "dist\ezClipping-$version.zip"
Compress-Archive -Force -DestinationPath $zip -Path dist\ezClipping.exe, dist\LICENSE, dist\THIRD-PARTY-NOTICES.md, `
    dist\README.md, dist\licenses
Get-FileHash dist\ezClipping.exe, $zip -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash.ToLower())  $(Split-Path $_.Path -Leaf)" } | Set-Content -Encoding ascii dist\SHA256SUMS.txt
Get-ChildItem dist -File | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
Get-Content dist\SHA256SUMS.txt
