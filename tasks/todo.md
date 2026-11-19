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

- [x] **T3: OBS → vertical clip (no gate yet)**. Done: Ctrl+L in your OBS → 29.6 s replay → vertical clip 17 s later.
  Reconnected after 3 OBS restarts. obsws-python's password/traceback logging silenced.
  - Does: `obs.py`: read websocket config (port/password) from `%APPDATA%\obs-studio\plugin_config\obs-websocket\config.json`, connect with retry, handle `ReplayBufferSaved` → `render.run`. Minimal `__main__.py` with config load/save.
  - Acceptance:
    - Ctrl+L in OBS → `<replay folder>\vertical\*_vertical.mp4` appears.
    - Closing and reopening OBS → reconnects within ~5 s, no crash.
  - Verify: unit tests for websocket config parsing + config round-trip. Manual check with real OBS.
  - Files: `ezclipping/obs.py`, `ezclipping/__main__.py`, `tests/test_obs.py`
  - Size: S–M

- [x] **T4: Clip button**. Done: Mouse 4 in Apex → instant beep + save. One save per press (probe-verified), plus a
  5 s cooldown against double presses. Low beep = didn't save. Replay buffer auto-starts on connect.
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

- [x] **T5: Queue + out-of-match gate + pause/resume**. Done, live over ~1.5 h of ranked: no render in a match,
  paused in the same check the bar came back, resumed 60 s after the match ended. Queue survived a hard kill. Job object
  kills ffmpeg if ezClipping dies. Lobby false-positive found and fixed. Idle: 0.1% of one core, 21 MB.
  - Does: saves go to `queue.json`. Gate loop every 3 s takes an OBS screenshot and runs `hud.visible`. 60 s without the bar (or OBS gone) → render the next job. Bar back → suspend ffmpeg, resume after the next 60 s gap.
  - Acceptance:
    - No ffmpeg process while the bar is visible.
    - Render suspends within ~3 s of the bar returning.
    - Quit with jobs queued → restart → they render. A half-finished render restarts cleanly and leaves no `.part` file behind.
  - Verify: unit tests for the gate (pure function: timestamps + visible flags → start/suspend/resume/wait) and queue persistence. Manual check with OBS.
  - Files: `ezclipping/__main__.py`, `ezclipping/render.py`, `ezclipping/obs.py`, `tests/test_gate.py`
  - Size: M

- [x] **T6: Tray + start with Windows**. Done: tray icon (gray until OBS connects), live status tooltip, double-click
  opens the clips folder, Start with Windows toggle (registry Run key), Quit stops cleanly. A second copy refuses to start.
  The Run-key command was checked by launching it from C:\ via CreateProcess. A real reboot happens on your next login.
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

- [x] **T7: Settings window**. Done: native ttk window from the tray (and opens itself on first run). Clip button
  capture (no left/right mouse, Esc cancels), resolution presets + custom (accepts -w 2200 -h 1440), OBS auto/manual with
  live status, 3 toggles. Saves apply live (new button worked instantly); bad input shows an inline error.
  - Does: tkinter window. OBS host/port/password (pre-filled from auto-read), clip button "press a key or mouse button" capture, in-game resolution dropdown + custom `W x H`, toggles (beep, auto-start replay buffer, start with Windows). Changes apply without a restart.
  - Acceptance:
    - Change the button or resolution → it takes effect immediately.
    - Bad input (custom res `abc`) shows an error and isn't saved.
  - Verify: unit test for resolution parsing. Manual check.
  - Files: `ezclipping/settings.py`, `ezclipping/hotkey.py`, `ezclipping/__main__.py`, `tests/test_settings.py`
  - Size: M

- [x] **T8: Calibrate + Preview**. Done: drag a box on a live OBS screenshot. It checks right away that the HP bar
  is inside (the pause-in-match check depends on it). Preview renders one real frame in 0.17 s. Reset goes back to
  the formula. Tested by you in the Firing Range.
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

- [x] **T9: Single exe**. Done: `build.ps1` → dist\ezClipping.exe 54.5 MB (+ FFMPEG-LICENSE.txt, README.md), builds
  in 25 s, starts in 2.1 s, 64 MB RAM. Fresh-config run through Explorer: settings opened by themselves, the clip
  button saved, and a 208 s clip rendered with the bundled ffmpeg (seen running from the exe's _MEI dir). Checkpoint D
  covered by this.
  - Does: `build.ps1` copies ffmpeg.exe + its license into `vendor\` and runs PyInstaller `--onefile --noconsole`. The app finds the bundled ffmpeg. README covers user setup (enable OBS websocket, replay buffer, pick button/res) and the SmartScreen note.
  - Acceptance:
    - `dist\ezClipping.exe` works with Python and ffmpeg off PATH.
    - Size noted.
  - Verify: run the exe from a shell with a stripped PATH, full clip flow.
  - Files: `build.ps1`, `ezclipping/render.py`, `README.md`, `.gitignore`
  - Size: S

### Checkpoint E
- [x] All SPEC success criteria checked:
  1. Button saves: OBS accepts the save + beep instantly; the file is written and queued ~2 s later (OBS writing a
     long buffer). Mouse 4, Page Up, Shift and OBS's own Ctrl+L all tested.
  2. No ffmpeg during matches (T5 1.5 h log). Idle 0.1% of one core; RAM 21 MB dev, 64 MB exe. CPU during a match with
     clips queued not measured separately (same 3 s JPEG check, ~9 ms of OBS CPU each).
  3. 60 s gap → render, bar back → paused in the same check, resumed after the next gap (T5 log).
  4. Exe clip: 1080x1920, 60 fps, H.264 + AAC, 207.8 s = replay length, in `vertical\`.
  5. Layout positions: covered by tests (strip 352-1568, bar centered at 1382).
  6. 2200x1440 lines up uncalibrated (T1/T2). 1080p source renders (test).
  7. Calibrate → Preview shows the dragged box (you, T8).
  8. h264_nvenc on your PC, libx264 fallback (tests).
  9. Queue survived a hard kill and rendered after restart (T5).
  10. Exe used its own bundled ffmpeg and frozen Python. Not yet run on a PC that never had Python/ffmpeg.
  11. Reconnects within ~5 s of OBS opening (T3). Real reboot: your next login.
- [x] code-reviewer + security-auditor findings shown to you and fixed (all 9 bugs, all low security items, GPLv3
  release files). Each bug was reproduced by a failing test first. 75 → 111 tests.
  Not done on purpose: code signing (paid; SHA-256 published instead), `--require-hashes`/pip-audit, Python 3.13,
  two dev-only nits. Unticking "auto" still copies OBS's password into config (same storage as OBS's own file).
- [x] /ship run: NO-GO (gate can jam, no retry back-off, queue path normalization, tests touching real data,
  ffmpeg source duty). Decision: users install ffmpeg themselves (winget); not bundled.

## Phase 6: Release fixes (from /ship)

- [x] **R1: Gate can't jam, failures back off**. Done (13af59e): job cleared before finish/cancel, OSError = failed
  render, RETRY_AFTER x tries back-off, paths normalized, sleep isn't a hang. End-to-end gate test added.
  - Does: clear the job before finishing/cancelling, and treat OSError in finish/cancel as a failed render.
    Wait RETRY_AFTER x tries after a failure. Normalize queue paths on load. A start failure caused by the clip
    counts toward its tries. Sleep/hibernate doesn't count as "hung".
  - Verify: failing tests first for each (fake job with poll()=0 and a missing .part, etc.), plus an end-to-end
    gate test: hidden 61 s → start, visible → pause, hidden 61 s → resume, done → dequeued.
  - Files: `ezclipping/__main__.py`, `tests/test_retry.py`, `tests/test_gate.py`
- [x] **R2: Tests isolated and honest**. Done (c21ecd8): no test touches real %APPDATA% or OBS config, 0 false
  positives required, full libx264 render added, suite 21 s -> 15 s.
  - Does: no test reads your real queue.json or OBS config. The bad-host test asserts the error is logged.
    The HUD test needs 0 false positives, the pause test checks the file has data. Orphan test ~2 s.
    Adds a full libx264 render test.
  - Files: `tests/*`
- [x] **R3: Settings and config safety**. Done (ee5b744): unreadable config never overwritten, save errors shown in
  the window, registry errors logged, clip_key/host validated, leaving auto clears the password.
  - Does: an unreadable config.json is never overwritten. Save and registry errors are logged and shown in the
    window. clip_key must be capturable (no left/right mouse). Leaving "auto" clears the password. Host must
    match `[A-Za-z0-9.-]`.
  - Files: `ezclipping/__main__.py`, `ezclipping/settings.py`, `ezclipping/obs.py`, tests
- [x] **R4: ffmpeg from the user**. Done (1152e91): PATH, registry user PATH or winget folders (never cwd), 7.1+
  check, tray says missing, Install ffmpeg button, clips stay queued, protocol/format allow-list.
  - Does: find ffmpeg on PATH or in winget's folders, and require 7.1+ (the layout needs it). If it's missing,
    the tray says so and Settings shows an *Install ffmpeg* button that runs
    `winget install Gyan.FFmpeg.Essentials` in a console window. Clips stay queued until ffmpeg is found.
    ffmpeg may only open local files (`-protocol_whitelist file`).
  - Files: `ezclipping/render.py`, `ezclipping/__main__.py`, `ezclipping/settings.py`, tests
- [x] **R5: Release packaging**. Done: exe 57 -> 19.7 MB, no ffmpeg or JDK DLLs inside (checked with
  pyi-archive_viewer). Zip: exe, LICENSE, README, notices, licenses\ (8 texts; Python's covers VCRUNTIME, OpenSSL,
  Tcl/Tk). New exe started from C:\ at 49 MB. Your login autostart at 10:15 confirms the reboot check.
  - Does: no ffmpeg in the exe. Build with a clean PATH (no JDK DLLs). A `licenses\` folder in the zip with every
    bundled license text. Notices and README updated (ffmpeg install step).
  - Verify: build, smoke-test the exe through Explorer, check zip contents.
  - Files: `build.ps1`, `THIRD-PARTY-NOTICES.md`, `README.md`, `SPEC.md`

### Checkpoint F
- [x] Tests + lint green, exe rebuilt and run by you once (clip → render). Done: 10:50 save → rendered 60 s after
  the bar went away, in 31 s, with your winget ffmpeg. 1080x1920, 60 fps, H.264 + AAC, 81.22 s vs 81.24 s replay.
  **GO.**
- [x] Quick re-check of the changed areas: code-reviewer + security-auditor on 600c75f..HEAD. NO-GO, then fixed
  (a1e6f3e, 1d7f92a, 8353e0e), each reproduced by a failing test first, 135 -> 140 tests:
  stale ffmpeg path after a winget upgrade, relative winget paths without LOCALAPPDATA, broken winget alias did
  nothing, config read twice (a passing lock let defaults overwrite it), unreadable queue.json overwritten,
  disk full / antivirus / GPU fault dropped every clip after 3 tries, unplugged drive dropped clips, cancel could
  block on a stuck ffmpeg. build.ps1 now stops on Python failures. Exe rebuilt (19.7 MB), runs from C:\ at 49 MB.
  Not changed (out of scope for a local app): user-writable PATH folders, remote OBS host is unencrypted,
  hand-edited config with a remote host + port could get OBS's password on the next Save.
- [x] Published 2026-11-19: github.com/neojohnsson/ezClipping, release v0.1.0 (zip + SHA256SUMS, sums checked
  after download). Decided: test images keep only the pixels the detector reads (names
  and session ids blacked out, old versions too). Every commit's email is now the GitHub noreply address (history
  rewritten, nothing was ever pushed). Backup of the old history: `..\ezClipping-before-rewrite.bundle`, delete it
  once the push is done (it still has the unmasked images and your Gmail).
