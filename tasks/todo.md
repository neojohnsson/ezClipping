# ezClipping: Tasks

Commands: test `.venv\Scripts\python -m unittest discover -s tests -v` · lint `.venv\Scripts\ruff check .`
Each task ends with tests + lint green and a git commit.

## Phase 1: Core pipeline

- [x] **T1: Replay file → vertical clip**. Done: card-shaped mask added (matches reference), GPU decode (d3d11va),
  20 s of 1440p180 renders in 6 s on your PC (a 270 s replay ≈ 80 s). Box measured: `(0.0266, 0.896, 0.200, 0.0667)` at 2200x1440.
  - Does: `git init`, venv, requirements. `hud.box_for_res(w, h)` formula. `render.filter_graph(box)`,
    encoder detection (nvenc → amf → qsv → libx264), `render.run(src, dst)` at idle priority writing `.part` then renaming.
    `python -m ezclipping.render <replay>` for manual runs.
  - Acceptance:
    - Output 1080x1920, 60 fps, h264 + aac, duration within 0.1 s of the source. Gameplay strip 1080x1215 at y=352. Health bar 756 px wide centered at y≈1382.
    - A clip from your real footage, compared side by side with the reference, looks the same. Box numbers refined on your footage.
    - Picks `h264_nvenc` on your PC. Forcing it off falls back to `libx264`.
  - Verify: unit tests for box formula + graph. Integration test renders a 3 s `testsrc2` 2560x1440@180fps mkv and checks it with ffprobe. Render time noted for a 270 s replay.
  - Files: `ezclipping/__init__.py`, `ezclipping/hud.py`, `ezclipping/render.py`, `tests/test_render.py`, `requirements*.txt`, `.gitignore`
  - Size: M

- [x] **T2: Health-bar visible detector**. Done: 272/272 alive frames visible, 44/45 out-of-match hidden (1 intro frame),
  knocked 15/15 and spectating 10/10 count as hidden, 0.06 ms/frame, tolerates a box ~0.5% off. Lobby not covered yet (no footage).
  - Does: `hud.visible(img, box) -> bool` on a ~640 px frame. Labeled fixtures = small crops around the box from your recordings: alive (several shield colors, low HP), knocked, lobby, menus/loading, match summary.
  - Acceptance:
    - ≥ 95% correct on fixtures, and 0 alive-in-match frames marked "not visible".
    - Runs in < 5 ms per frame.
  - Verify: `tests/test_hud.py` over `tests/fixtures/hud/{visible,hidden}/*.png`.
  - Files: `ezclipping/hud.py`, `tests/test_hud.py`, `tests/fixtures/hud/**`
  - Size: S–M
  - Note: may need you to record a short lobby → match → death clip if the existing footage doesn't cover enough states.

### Checkpoint A
- [ ] Tests + lint green
- [ ] You review one rendered clip from your footage and the detector results

## Phase 2: End-to-end with OBS

- [ ] **T3: OBS → vertical clip (no gate yet)**
  - Does: `obs.py`: read websocket config (port/password) from `%APPDATA%\obs-studio\plugin_config\obs-websocket\config.json`, connect with retry, handle `ReplayBufferSaved` → `render.run`. Minimal `__main__.py` with config load/save.
  - Acceptance:
    - Ctrl+L in OBS → `<replay folder>\vertical\*_vertical.mp4` appears.
    - Closing and reopening OBS → reconnects within ~5 s, no crash.
  - Verify: unit tests for websocket config parsing + config round-trip. Manual check with real OBS.
  - Files: `ezclipping/obs.py`, `ezclipping/__main__.py`, `tests/test_obs.py`
  - Size: S–M

- [ ] **T4: Clip button**
  - Does: `hotkey.py` polls `GetAsyncKeyState` at ~30 Hz with edge detection (fires once per press). On press: `SaveReplayBuffer` + beep. On connect: start the replay buffer if it's off (toggle).
  - Acceptance:
    - Keyboard key and mouse side button both trigger a save while Apex is focused.
    - One press = one save, even if held.
    - No input lag (nothing hooks input).
  - Verify: unit test for edge detection (pure function over key states). Manual check in Apex.
  - Files: `ezclipping/hotkey.py`, `ezclipping/obs.py`, `ezclipping/__main__.py`, `tests/test_hotkey.py`
  - Size: S

### Checkpoint B
- [ ] Tests + lint green
- [ ] You press your button in Apex → vertical clip appears

## Phase 3: Zero-impact gating + tray

- [ ] **T5: Queue + out-of-match gate + pause/resume**
  - Does: saves go to `queue.json`. Gate loop every 3 s takes an OBS screenshot and runs `hud.visible`. 60 s without the bar (or OBS gone) → render the next job. Bar back → suspend ffmpeg, resume after the next 60 s gap.
  - Acceptance:
    - No ffmpeg process while the bar is visible.
    - Render suspends within ~3 s of the bar returning.
    - Quit with jobs queued → restart → they render. A half-finished render restarts cleanly and leaves no `.part` file behind.
  - Verify: unit tests for the gate (pure function: timestamps + visible flags → start/suspend/resume/wait) and queue persistence. Manual check with OBS.
  - Files: `ezclipping/__main__.py`, `ezclipping/render.py`, `ezclipping/obs.py`, `tests/test_gate.py`
  - Size: M

- [ ] **T6: Tray + start with Windows**
  - Does: pystray icon. Tooltip shows connected / queue count / rendering. Menu: Settings, Open clips folder, Quit. Startup-folder shortcut on/off.
  - Acceptance:
    - The icon shows its states.
    - Quit stops cleanly; a suspended ffmpeg is killed and its job stays queued.
    - After a reboot it's in the tray.
  - Verify: manual check, plus a reboot test.
  - Files: `ezclipping/__main__.py`
  - Size: S

### Checkpoint C
- [ ] Tests + lint green
- [ ] Real play session with you: ezClipping < 1% CPU and < 100 MB RAM during the match, no ffmpeg during the match, clips render in lobby
- [ ] OBS CPU/GPU no different with ezClipping running

## Phase 4: Settings for other users

- [ ] **T7: Settings window**
  - Does: tkinter window. OBS host/port/password (pre-filled from auto-read), clip button "press a key or mouse button" capture, in-game resolution dropdown + custom `W x H`, toggles (beep, auto-start replay buffer, start with Windows). Changes apply without a restart.
  - Acceptance:
    - Change the button or resolution → it takes effect immediately.
    - Bad input (custom res `abc`) shows an error and isn't saved.
  - Verify: unit test for resolution parsing. Manual check.
  - Files: `ezclipping/settings.py`, `ezclipping/hotkey.py`, `ezclipping/__main__.py`, `tests/test_settings.py`
  - Size: M

- [ ] **T8: Calibrate + Preview**
  - Does: grab a full-res OBS screenshot, show it scaled, drag a box → save fractions. Preview renders one 1080x1920 frame of the layout from that screenshot (same filter graph) and shows it.
  - Acceptance:
    - The dragged box shows up as the health-bar overlay in Preview.
    - "Reset" goes back to the formula.
  - Verify: unit test for the screen-to-fraction conversion. Manual check.
  - Files: `ezclipping/settings.py`, `ezclipping/render.py`, `tests/test_settings.py`
  - Size: M

### Checkpoint D
- [ ] Tests + lint green
- [ ] Delete config → set everything up through the UI only → clip works

## Phase 5: Ship

- [ ] **T9: Single exe**
  - Does: `build.ps1` copies ffmpeg.exe + its license into `vendor\` and runs PyInstaller `--onefile --noconsole`. The app finds the bundled ffmpeg. README covers user setup (enable OBS websocket, replay buffer, pick button/res) and the SmartScreen note.
  - Acceptance:
    - `dist\ezClipping.exe` works with Python and ffmpeg off PATH.
    - Size noted.
  - Verify: run the exe from a shell with a stripped PATH, full clip flow.
  - Files: `build.ps1`, `ezclipping/render.py`, `README.md`, `.gitignore`
  - Size: S

### Checkpoint E
- [ ] All SPEC success criteria checked
- [ ] code-reviewer agent findings shown to you and fixed
- [ ] /ship before you share it
