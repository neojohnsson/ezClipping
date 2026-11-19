# Spec: ezClipping

## Objective
A free Windows tray app for Apex Legends players who stream/record with OBS. Press your clip button
and the OBS Replay Buffer is saved. Once you're out of the match, the app turns that replay into a
9:16 vertical clip ready for TikTok / YouTube Shorts / Reels, laid out like the reference image:

```
 1080 x 1920
┌──────────────┐
│ blurred bg   │  same frame, zoomed to fill, heavy blur
├──────────────┤  y = 352
│              │
│  gameplay    │  center 50% of frame width, full height -> 1080 x 1215 (16:9 source)
│ [health bar] │  own health bar, 756 px wide (70%), centered, middle at y ≈ 1382 (72%)
│              │
├──────────────┤  y = 1567
│ blurred bg   │
└──────────────┘
```

Users: you first, then other Apex players (shareable single .exe, no Python needed; ffmpeg installed with one click via winget).
"Zero performance": nothing heavy ever runs while you're alive in a match.

### User stories / acceptance
1. I set my clip button in the app: any keyboard key or mouse button (incl. side buttons).
   Pressing it in-game saves the OBS replay. Adds no input lag.
2. Saving a replay with OBS's own hotkey also gets converted.
3. Every saved replay (full length, whatever the OBS buffer is) goes into a queue. The original is never touched.
4. While my health bar is on screen, no rendering happens.
5. When my health bar has been gone for 60 s (lobby, menus, dead, Apex closed, OBS closed), the queue renders.
   If my health bar comes back mid-render, the render is suspended and resumes later.
6. Output lands in `<replay folder>\vertical\<replay name>_vertical.mp4`.
7. In settings I pick: OBS connection, clip button, my in-game resolution. A "Calibrate" button lets me
   drag a box over my health bar on a live screenshot, and "Preview" shows one frame of the final layout.

## Assumptions (correct me now or I'll go with these)
1. **Stack:** Python 3.12, tkinter (built in) for the settings window, `pystray` + `Pillow` for the tray and images,
   `obsws-python` for obs-websocket v5. Packaged with PyInstaller as one .exe. ffmpeg is not bundled: the user installs it (winget).
2. **Clip button:** polls `GetAsyncKeyState` about 30x/s. No keyboard/mouse hooks, so no added input lag and nothing
   anti-cheat cares about. Cost is effectively zero.
3. **OBS password:** auto-read from `%APPDATA%\obs-studio\plugin_config\obs-websocket\config.json` each connect.
   Typing it in manually is the fallback (stored in the app's config, same trust level as OBS's own file).
4. **Replay buffer:** if it's off when the app connects, the app starts it (toggle in settings, default on).
5. **Feedback:** short Windows sound when a replay is saved, so you know it worked mid-fight (toggle, default on).
6. **Encoder:** first one that works out of `h264_nvenc` → `h264_amf` → `h264_qsv` → `libx264`. ~20 Mbps H.264 + AAC 192k,
   mp4 with faststart. ffmpeg runs at idle CPU priority.
7. **Audio:** OBS audio track 1 only.
8. **Startup:** starts with Windows (shortcut in the user's Startup folder, toggle in settings, default on).
   Sits in the tray doing nothing until OBS is open, then reconnects automatically whenever OBS comes and goes.

## Layout math (relative, so any source resolution works)
Source frame W x H (whatever OBS records, e.g. 2560x1440 or 1920x1080). Output 1080 x 1920 @ 60 fps.

| Layer | Source crop | Output |
|---|---|---|
| Background | center `H*9/16 x H` | downscale to 1/8, box blur, upscale to 1080x1920 (cheap blur) |
| Gameplay | center `W/2 x H` | scale to width 1080, vertically centered |
| Health bar | preset/calibrated box (fractions of W, H) | scale to width 756, centered x, middle at y = 0.72 * 1920 |

Health-bar box from the **in-game** resolution `Wg x Hg` (aspect `A = Wg/Hg`), as fractions of the recorded frame.
The Apex HUD sits a fixed distance from the bottom-left, in units of screen height, so one formula covers every
resolution, stretched or not:

```
box = (x = 0.0474 / A,  y = 0.896,  w = 0.298 / A,  h = 0.0625)
```

| In-game res | A | Box (x, y, w, h) | Source |
|---|---|---|---|
| 2200x1440 (stretched, yours) | 1.528 | `(0.031, 0.896, 0.195, 0.0625)` | measured on your footage, refined in build |
| 16:9 (1920x1080, 2560x1440, ...) | 1.778 | `(0.027, 0.896, 0.168, 0.0625)` | from formula |
| 16:10 (1728x1080, 1680x1050) | 1.6 | `(0.030, 0.896, 0.186, 0.0625)` | from formula |
| 4:3 (1440x1080, 1280x960) | 1.333 | `(0.036, 0.896, 0.224, 0.0625)` | from formula |

The settings dropdown lists common resolutions plus a custom `W x H` field (e.g. `-w 2200 -h 1440`).
Assumes OBS stretches the game to fill the canvas, with no black bars. If not, Calibrate covers it.
A calibrated box always wins over the formula.

## Tech Stack
- Python 3.12 (`py -3.12`)
- Runtime deps: `obsws-python`, `pystray`, `Pillow` (pinned in `requirements.txt`)
- Dev deps: `pyinstaller`, `ruff` (pinned in `requirements-dev.txt`)
- ffmpeg 7.1+ installed by the user (`winget install Gyan.FFmpeg.Essentials`, offered from Settings). Found on PATH or in winget's folders.
- OBS Studio 28+ (obs-websocket v5 is built in)

## Commands
```
Setup:  py -3.12 -m venv .venv; .venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
Run:    .venv\Scripts\python -m ezclipping
Test:   .venv\Scripts\python -m unittest discover -s tests -v
Lint:   .venv\Scripts\ruff check .
Build:  .\build.ps1        # PyInstaller --onefile --noconsole -> dist\ezClipping.exe + release zip
```

## Project Structure
```
ezclipping/
  __main__.py   tray icon, wiring, config load/save, job queue + "out of match" gate loop
  obs.py        connect (auto password), save replay, ReplayBufferSaved events, tiny screenshots
  hotkey.py     GetAsyncKeyState polling + "press a key/button" capture for settings
  hud.py        health-bar presets + is-health-bar-visible check
  render.py     ffmpeg filter graph, encoder detection, run / suspend / resume
  settings.py   tkinter window: OBS, clip button, resolution, calibrate drag-box, preview
tests/
  test_render.py  filter graph math + real 3 s render checked with ffprobe
  test_hud.py     detector vs labeled frames
  fixtures/       a few real frames (in match / lobby / menu / summary) + short sample clip
vendor/ (gitignored, build.ps1 writes the icon there)
requirements.txt, requirements-dev.txt, build.ps1, SPEC.md
```
User data: `%APPDATA%\ezClipping\config.json` and `queue.json`.

## Code Style
Plain functions, small modules, stdlib first, no classes unless something holds state.
```python
def filter_graph(box: tuple[float, float, float, float]) -> str:
    """ffmpeg -filter_complex for the vertical layout. box = health bar as fractions of the frame."""
    x, y, w, h = box
    return (
        "[0:v]fps=60,split=3[a][b][c];"
        "[a]crop=ih*9/16:ih,scale=135:240,boxblur=6:2,scale=1080:1920[bg];"
        "[b]crop=iw/2:ih,scale=1080:-2[mid];"
        f"[c]crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},scale=756:-2[hb];"
        "[bg][mid]overlay=0:(H-h)/2[v];"
        "[v][hb]overlay=(W-w)/2:H*0.72-h/2[out]"
    )
```
- snake_case, type hints on public functions, no comments that restate code.
- Deliberate shortcuts get a `ponytail:` comment naming the limit.
- Ruff defaults, line length 110.

## Testing Strategy
- `unittest` (stdlib), tests in `tests/`.
- **Unit:** filter graph and layout positions, preset selection, config round-trip, password auto-read.
- **Detector:** `hud.py` against labeled real frames. Target ≥ 95% correct, and zero "not visible" on alive-in-match frames.
- **Integration:** render a 3 s fixture clip, then ffprobe checks 1080x1920, 60 fps, h264 + aac, duration within 0.1 s.
- **Manual (with you):** real OBS + Apex run. Clip with the button, play on, check no ffmpeg during the match,
  go to lobby, clip appears. Compare it side by side with the reference image.
- **Perf check:** during a match, ezClipping averages < 1% CPU and < 100 MB RAM (Task Manager / `Get-Process`).

## Boundaries
- **Always:** run tests + ruff before each commit. Write the output to a temp name, then rename (no half files).
  Run ffmpeg at idle priority. Keep queued jobs on disk so a crash or restart loses nothing.
- **Ask first:** adding any dependency not listed here. Changing the layout numbers. Touching OBS settings
  beyond starting the replay buffer.
- **Never:** keyboard/mouse hooks, reading or injecting into the game process, anything anti-cheat could flag.
  Modify or delete original replays. Network calls other than localhost OBS. Telemetry. Commit secrets.

## Success Criteria
1. Button press (keyboard and mouse side button) → replay saved and queued within 1 s. OBS's own hotkey also queues.
2. No ffmpeg process while the health bar is visible. ezClipping < 1% CPU avg, < 100 MB RAM during a match.
3. Health bar gone 60 s → render starts. Bar back → render suspended within ~3 s, resumes after the next 60 s gap.
4. Output is 1080x1920, 60 fps, H.264 + AAC mp4, same length as the replay, in `<replay folder>\vertical\`.
5. 16:9 layout: gameplay 1080x1215 at y=352, health bar 756 px wide centered at y≈1382. Looks like the reference.
6. Your 2200x1440-stretched recordings line up with no calibration. The same in-game res recorded at 1080p or 1440p in OBS also works.
7. Calibrate → Preview shows the dragged box as the health-bar overlay.
8. Picks `h264_nvenc` on your PC, falls back to `libx264` when no GPU encoder works.
9. Quit with clips queued → restart → they still render.
10. `dist\ezClipping.exe` runs on a PC without Python. Without ffmpeg it says so, offers the winget install, and keeps clips queued.
11. After a reboot it's in the tray, and it connects within ~5 s of OBS opening, with no clicks needed.

## Open Questions
1. Only 2200x1440 is measured. Other resolutions come from the formula. Calibrate covers any miss, and a native 16:9 screenshot would confirm the formula.
2. ffmpeg isn't shipped, so its GPL source duty isn't ours. ezClipping itself is GPLv3 (obsws-python is GPL).
