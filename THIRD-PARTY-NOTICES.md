# Third-party software

ezClipping is free software under the GNU General Public License v3 (see `LICENSE`). The full source code of each
version is published with its release, together with the build script that makes `ezClipping.exe`.

## Inside ezClipping.exe

`ezClipping.exe` bundles the software below, each under its own license. Their license texts are in the
`licenses` folder next to the exe.

| Component | Version | License | Source |
|---|---|---|---|
| obsws-python | 1.8.1 | GPL-3.0-only | https://github.com/aatikturk/obsws-python |
| pystray | 0.19.5 | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| Pillow (with the image libraries it bundles: libjpeg-turbo, zlib, FreeType and others; see its license file) | 13.0.0 | MIT-CMU | https://github.com/python-pillow/Pillow |
| websocket-client | 1.9.2 | Apache-2.0 | https://github.com/websocket-client/websocket-client |
| six | 1.17.0 | MIT | https://github.com/benjaminp/six |
| Python (CPython), with OpenSSL, libffi, Tcl/Tk, zlib, bzip2 and xz as built into its Windows release | 3.12 | PSF License 2.0 and the licenses in `python-LICENSE.txt` | https://www.python.org/downloads/source/ |
| PyInstaller bootloader | 6.22.3 | GPL-2.0-or-later with the bootloader exception | https://github.com/pyinstaller/pyinstaller |

pystray is LGPL: you can rebuild `ezClipping.exe` with your own version of it using `build.ps1` from the source.

## Not included: FFmpeg

ezClipping uses FFmpeg to make the clips, but does not ship it. You install it yourself (ezClipping offers to run
`winget install Gyan.FFmpeg.Essentials` for you), and it comes with its own license (GPL-3.0) and source from
https://ffmpeg.org and https://www.gyan.dev/ffmpeg/builds/.
