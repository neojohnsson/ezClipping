# Third-party software in ezClipping.exe

ezClipping is free software under the GNU General Public License v3 (see `LICENSE`). The full source code of each
version is published with its release, together with the build script that makes `ezClipping.exe`.

`ezClipping.exe` bundles the software below, each under its own license.

| Component | Version | License | Source |
|---|---|---|---|
| FFmpeg, gyan.dev "essentials" build | 8.0 | GPL-3.0-or-later (built with `--enable-gpl --enable-version3`), text in `FFMPEG-LICENSE.txt` | https://ffmpeg.org/releases/ffmpeg-8.0.tar.xz (also attached to each ezClipping release); build details: https://www.gyan.dev/ffmpeg/builds/ |
| obsws-python | 1.8.1 | GPL-3.0-only | https://github.com/aatikturk/obsws-python |
| pystray | 0.19.5 | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| Pillow | 13.0.0 | MIT-CMU | https://github.com/python-pillow/Pillow |
| websocket-client | 1.9.2 | Apache-2.0 | https://github.com/websocket-client/websocket-client |
| six | 1.17.0 | MIT | https://github.com/benjaminp/six |
| Python (CPython) | 3.12 | PSF License 2.0 | https://www.python.org/downloads/source/ |
| Tcl/Tk | 8.6 | Tcl/Tk license (BSD-style) | https://www.tcl.tk/software/tcltk/ |
| PyInstaller bootloader | 6.22.3 | GPL-2.0-or-later with the bootloader exception | https://github.com/pyinstaller/pyinstaller |

pystray is LGPL: you can rebuild `ezClipping.exe` with your own version of it using `build.ps1` from the source.

## FFmpeg build configuration

The bundled `ffmpeg.exe` reports this configuration (`ffmpeg -version`), which lists the libraries inside it:

```
ffmpeg version 8.0-essentials_build-www.gyan.dev
--enable-gpl --enable-version3 --enable-static --disable-w32threads --disable-autodetect --enable-fontconfig
--enable-iconv --enable-gnutls --enable-libxml2 --enable-gmp --enable-bzlib --enable-lzma --enable-zlib
--enable-libsrt --enable-libssh --enable-libzmq --enable-avisynth --enable-sdl2 --enable-libwebp --enable-libx264
--enable-libx265 --enable-libxvid --enable-libaom --enable-libopenjpeg --enable-libvpx --enable-mediafoundation
--enable-libass --enable-libfreetype --enable-libfribidi --enable-libharfbuzz --enable-libvidstab --enable-libvmaf
--enable-libzimg --enable-amf --enable-cuda-llvm --enable-cuvid --enable-dxva2 --enable-d3d11va --enable-d3d12va
--enable-ffnvcodec --enable-libvpl --enable-nvdec --enable-nvenc --enable-vaapi --enable-openal --enable-libgme
--enable-libopenmpt --enable-libopencore-amrwb --enable-libmp3lame --enable-libtheora --enable-libvo-amrwbenc
--enable-libgsm --enable-libopencore-amrnb --enable-libopus --enable-libspeex --enable-libvorbis --enable-librubberband
```
