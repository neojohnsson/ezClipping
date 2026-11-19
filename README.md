# ezClipping

Press one button while you play Apex Legends and OBS saves the replay. When you're out of the match, ezClipping
turns it into a 1080x1920 vertical clip for TikTok, YouTube Shorts and Reels: blurred background, the middle of
your screen, and your health bar enlarged near the bottom.

It never renders while you're alive in a match. While it waits it uses next to no CPU.

## What you need

- Windows 10 or 11
- OBS Studio 28 or newer
- FFmpeg 7.1 or newer (free; ezClipping installs it for you with one click, see step 4)
- Apex Legends (any resolution, stretched too)

## Setup (5 minutes)

1. **OBS: turn on the WebSocket server.** Tools > WebSocket Server Settings > tick *Enable WebSocket server*.
   ezClipping reads the port and password from OBS by itself.
2. **OBS: turn on the replay buffer.** Settings > Output > Replay Buffer > tick *Enable Replay Buffer* and set
   *Maximum Replay Time* to how long you want each clip (30-60 s is good for Shorts). ezClipping starts the replay
   buffer for you whenever OBS is open.
3. **Give it its own folder, then run it.** Move `ezClipping.exe` into a folder of its own first, for example
   `%LOCALAPPDATA%\Programs\ezClipping`, not Downloads: it starts with Windows from wherever it is. Check that its
   SHA-256 matches the one on the release page. Windows may say "Windows protected your PC" because the app isn't
   signed. Click *More info* > *Run anyway*.
4. **Settings open by themselves.** If FFmpeg isn't installed yet, click *Install ffmpeg*: a window opens and
   winget installs it (or run `winget install Gyan.FFmpeg.Essentials` yourself). Then pick your clip button (any
   key or mouse button) and your in-game resolution, for example `2200 x 1440` or `-w 2200 -h 1440`. Click *Save*.
5. **Check the health bar.** In the Firing Range, open Settings from the tray icon and click *Preview*. If the
   health bar isn't framed right, click *Calibrate* and drag a box around it.

## Using it

- Press your clip button in-game. A short beep means OBS is saving the replay; a low beep means it couldn't
  (is OBS open?).
- Clips render about a minute after your match ends and land in a `vertical` folder next to your OBS recordings.
  Double-click the tray icon to open it.
- If a new match starts while a clip is rendering, the render pauses and picks up again after the match.
- The tray icon is gray until OBS is connected. Hover it to see what ezClipping is doing.

## Troubleshooting

- **Log:** `%APPDATA%\ezClipping\ezclipping.log`. When asking for help, send only that file, not the whole folder:
  `config.json` next to it can hold your OBS password.
- **Nothing happens when I press my button:** is the tray icon red (OBS connected)? Is the replay buffer enabled in
  OBS? The log says why a save failed.
- **The health bar is in the wrong place:** Settings > Calibrate.
- **Tray says "ffmpeg not installed":** open Settings and click *Install ffmpeg*. Clips you saved meanwhile wait
  and render once it's there.

## License

ezClipping is free software under the GNU General Public License v3 (`LICENSE`). It bundles a few Python
libraries under their own licenses (`THIRD-PARTY-NOTICES.md`, texts in `licenses`). FFmpeg is not included.

## Development

```
py -3.12 -m venv .venv; .venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python -m ezclipping                    # run
.venv\Scripts\python -m unittest discover -s tests    # test (needs ffmpeg + ffprobe on PATH)
.venv\Scripts\ruff check .                            # lint
.\build.ps1                                           # dist\ezClipping.exe + release zip + SHA256SUMS.txt
```

### Releasing

1. Bump `__version__` in `ezclipping/__init__.py`, run the tests, run `.\build.ps1`.
2. Push the commit and tag it (`v0.1.0`); the repository is the source code GPLv3 asks you to offer.
3. Make a GitHub release from the tag and attach `dist\ezClipping-<version>.zip` and `dist\SHA256SUMS.txt`.
4. Paste the SHA-256 lines into the release notes.
