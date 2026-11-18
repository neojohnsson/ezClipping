# Implementation Plan: ezClipping

## Overview
A Windows tray app that turns OBS Replay Buffer saves of Apex Legends into 1080x1920 vertical clips (blurred
background, center gameplay, enlarged health bar). Rendering only runs once the health bar has been gone for
60 s. Shipped as one .exe. Full requirements are in `SPEC.md`.

## Architecture Decisions
- **ffmpeg does all video work** in one `-filter_complex` pass, using relative crops (`iw`, `ih`) so it doesn't need to know the source resolution. No ffprobe in the app.
- **Health-bar box = formula from in-game res** (`x=0.0474/A, w=0.298/A, y=0.896, h=0.0625`). A calibrated box overrides it. The same box drives both the overlay and the in-match check.
- **Out-of-match gate = health-bar check** on a ~640 px OBS screenshot every 3 s. OBS closed or unreachable counts as "out of match". That also covers "Apex closed", so no process watching is needed.
- **Pause = suspend the ffmpeg process** (`NtSuspendProcess` via ctypes), not kill/restart, so no work is lost.
- **Clip button = `GetAsyncKeyState` polling** at ~30 Hz. No hooks, no input lag, anti-cheat safe.
- **State on disk:** `%APPDATA%\ezClipping\config.json` and `queue.json`. Jobs survive restarts.
- **Render writes `*.part.mp4`, then renames.** Originals are never touched.
- **Tests use synthetic video** (ffmpeg `testsrc2`) plus small health-bar crops. No webcam or chat footage goes in the repo.

## Dependency Graph
```
hud.box_for_res ──┬─> render.filter_graph ──> render.run (encoder detect, idle prio)
                  │                                  │
                  └─> hud.visible (detector)         │
                                │                    │
obs.connect / events / screenshot ──> __main__ (queue + gate loop) <── hotkey.poll
                                                     │
                                          tray ──> settings (calibrate/preview uses obs.screenshot + render)
                                                     │
                                                 build.ps1 (exe)
```

## Task List (details + acceptance in `tasks/todo.md`)

### Phase 1: Core pipeline (riskiest first)
- [ ] T1 Replay file → vertical clip (render + box formula), visual match vs reference
- [ ] T2 Health-bar visible detector, tuned on real labeled frames

### Checkpoint A: you look at a rendered clip from your footage + detector results

### Phase 2: End-to-end with OBS
- [ ] T3 OBS connect + ReplayBufferSaved → vertical clip (ungated)
- [ ] T4 Clip button (key/mouse) → SaveReplayBuffer, beep, auto-start replay buffer

### Checkpoint B: press your button in Apex → vertical clip appears

### Phase 3: Zero-impact gating + tray
- [ ] T5 Persisted queue + out-of-match gate + suspend/resume
- [ ] T6 Tray icon (status, open folder, settings, quit) + start with Windows

### Checkpoint C: real play session, perf check (< 1% CPU, < 100 MB, no ffmpeg in match)

### Phase 4: Settings for other users
- [ ] T7 Settings window (OBS, clip button capture, resolution + custom WxH, toggles)
- [ ] T8 Calibrate drag-box + Preview frame

### Checkpoint D: a fresh config works start to finish through the UI only

### Phase 5: Ship
- [ ] T9 build.ps1 → single exe with ffmpeg + license, README for users

### Checkpoint E: exe runs without Python/ffmpeg on PATH, then code-reviewer agent, then /ship

## Risks and Mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| Detector says "no health bar" while you're alive (render starts mid-fight) | High | Tune on many real frames (BR + mixtape, all shield colors, low HP, knocked). When unsure, treat as visible. Require 60 s of continuous absence. Suspend as soon as the bar is back. |
| Formula box wrong for native 16:9 / other res | Med | Calibrate + Preview in T8. Ask for one native 16:9 screenshot later. |
| 180 fps HEVC 1440p source makes renders slow | Low | Renders only run out of match. Measure in T1. Try `-hwaccel d3d11va` decode if slow. |
| `GetAsyncKeyState` doesn't see keys while Apex has focus | Med | Verify in T4 on your PC first. Fallback is Raw Input (`RIDEV_INPUTSINK`), still hook-free. |
| obsws-python hangs or throws when OBS closes | Med | Reconnect loop with timeouts in T3. Test by closing OBS mid-session. |
| Unsigned PyInstaller exe → SmartScreen warning / antivirus false positive | Med (sharing) | README explains "More info → Run anyway". Code signing is a later, paid decision. |
| OBS screenshot every 3 s costs OBS performance | Low | 640 px JPG. Measure OBS CPU/GPU in Checkpoint C. Raise interval if needed. |

## Open Questions
- Where you'll share the exe (GitHub Releases, Discord, ...). Not needed until T9.
- Code signing (paid) to avoid SmartScreen warnings. Decide after people try it.
