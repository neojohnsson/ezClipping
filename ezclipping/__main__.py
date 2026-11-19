"""ezClipping: every OBS replay you save becomes a 1080x1920 vertical clip."""

import ctypes
import json
import logging
import os
import sys
import threading
import time
import winreg
import winsound
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from ezclipping import hotkey, obs, render, settings
from ezclipping.hud import Box, box_for_res, valid_box, valid_res, visible

APP_DIR = Path(os.environ.get("APPDATA", "")) / "ezClipping"
CONFIG = APP_DIR / "config.json"
JOBS = APP_DIR / "queue.json"  # replays waiting to be rendered, survives restarts
CHECK_EVERY = 3  # s between health-bar checks (only while clips are waiting)
CLEAR_AFTER = 60  # s without your health bar on screen before rendering starts
MAX_TRIES = 3  # failed renders before a clip is given up on (the replay itself is never touched)
RETRY_AFTER = 60  # s to wait when ffmpeg can't even start (missing ffmpeg, broken GPU driver)
STALL_AFTER = 300  # s without the output growing (and not paused) = ffmpeg is hung
DEFAULTS = {
    "host": "localhost",
    "port": None,  # None = read port/password from OBS's own websocket config on every connect
    "password": None,
    "game_res": [1920, 1080],  # in-game resolution, decides where the health bar is
    "box": None,  # calibrated health-bar box (fractions), overrides game_res
    "clip_key": None,  # Windows virtual-key code of the clip button, e.g. 5 = mouse back button
    "beep": True,  # short sound when a replay is saved
    "auto_replay_buffer": True,  # start OBS's replay buffer when we connect
    "start_with_windows": True,
}
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
ERROR_ALREADY_EXISTS = 183
SAVE_COOLDOWN = 5  # s; a second save right after one is the same footage, and a second render
log = logging.getLogger("ezclipping")


# Every value config.json may hold, and what counts as valid (other software can edit the file).
CHECKS = {
    "host": lambda v: isinstance(v, str) and obs.valid_host(v),
    "port": lambda v: v is None or (type(v) is int and 1 <= v <= 65535),
    "password": lambda v: v is None or isinstance(v, str),
    "game_res": lambda v: (isinstance(v, list) and len(v) == 2 and all(type(n) is int for n in v)
                           and valid_res(*v)),
    "box": lambda v: v is None or valid_box(v),
    "clip_key": lambda v: v is None or (type(v) is int and v in hotkey.CAPTURABLE),  # never left/right mouse
    "beep": lambda v: isinstance(v, bool),
    "auto_replay_buffer": lambda v: isinstance(v, bool),
    "start_with_windows": lambda v: isinstance(v, bool),
}
_write_lock = threading.Lock()  # the tray and the settings window can both save at once


def write_json(path: Path, data) -> None:
    """Atomic and durable: a crash or power cut leaves either the old file or the new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)


def read_json(path: Path, default):
    """The file's JSON, or default. A damaged file is kept aside as *.bad.json, never overwritten."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    except OSError as e:
        log.error("Couldn't read %s: %s", path, e)
        return default
    try:
        return json.loads(text)
    except ValueError:
        bad = path.with_suffix(".bad.json")
        try:
            path.replace(bad)
        except OSError:
            pass  # locked: it just stays where it is
        log.error("%s was damaged; kept it as %s and started fresh", path.name, bad.name)
        return default


def clean_config(raw) -> dict:
    """Defaults, overridden by every valid value in raw."""
    cfg = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return cfg
    for key, value in raw.items():
        if key in CHECKS and CHECKS[key](value):
            cfg[key] = value
        elif key in CHECKS:
            log.warning("Ignoring an invalid %s in config.json", key)  # never log the value: could be the password
    return cfg


def load_config(path: Path = CONFIG) -> dict:
    return clean_config(read_json(path, {}))


def connection_password(cfg: dict, ws: dict) -> str:
    """The typed password, else OBS's own, but OBS's own only for this PC: never sent to another machine."""
    if cfg["password"] is not None:
        return cfg["password"]
    return ws.get("password", "") if cfg["host"] in obs.LOOPBACK else ""


def save_config(cfg: dict, path: Path = CONFIG) -> None:
    write_json(path, cfg)


def unreadable(path: Path) -> bool:
    """True if the file exists but can't be read (locked, no permission): then it must not be overwritten."""
    try:
        path.read_bytes()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return False


def clip_box(cfg: dict) -> Box:
    return tuple(cfg["box"]) if cfg["box"] else box_for_res(*cfg["game_res"])


def tray_image(connected: bool) -> Image.Image:
    """A vertical clip with a play mark on a dark tile. Gray while OBS isn't connected."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((2, 2, 62, 62), radius=14, fill=(24, 24, 30, 255))
    draw.rounded_rectangle((20, 9, 44, 55), radius=5, fill=(255, 70, 85, 255) if connected else (110, 110, 118, 255))
    draw.polygon([(28, 23), (28, 41), (41, 32)], fill=(255, 255, 255, 255))
    return img


def startup_command() -> str:
    if getattr(sys, "frozen", False):  # the packaged exe
        return f'"{sys.executable}"'
    # dev run: pythonw = no console window; works whatever folder Windows starts it in
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    root = Path(__file__).resolve().parent.parent
    return (f'"{pythonw}" -c "import sys, runpy; sys.path.insert(0, r\'{root}\'); '
            f'runpy.run_module(\'ezclipping\', run_name=\'__main__\')"')


def set_start_with_windows(on: bool, key: str = RUN_KEY, name: str = "ezClipping") -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        if on:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass


def starts_with_windows(key: str = RUN_KEY, name: str = "ezClipping") -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.QueryValueEx(k, name)
        return True
    except FileNotFoundError:
        return False


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = ctypes.c_void_p
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
_mutexes: list[int] = []  # held open until the process exits


def single_instance(name: str = r"Local\ezClipping") -> bool:
    """False if ezClipping is already running (two copies would save and render every clip twice)."""
    _mutexes.append(_kernel32.CreateMutexW(None, False, name))
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def decide(clear: bool, rendering: bool, suspended: bool, waiting: bool) -> str:
    """What the render gate does now. clear = health bar gone for CLEAR_AFTER s (out of match)."""
    if rendering and not clear and not suspended:
        return "suspend"
    if rendering and clear and suspended:
        return "resume"
    if not rendering and clear and waiting:
        return "start"
    return "wait"


class App:
    def __init__(self, cfg: dict, jobs_path: Path, config_path: Path | None = None):
        # jobs_path has no default so tests can't touch the real queue; config_path None = never write config
        self.cfg = cfg
        self.config_path = config_path
        self.stop = threading.Event()
        self.conn: obs.Obs | None = None
        self.last_save = -SAVE_COOLDOWN
        self.last_seen = time.monotonic()  # when your health bar was last on screen
        self.job: render.Job | None = None  # the render in progress
        self.suspended = False
        self.was_visible: bool | None = None  # health bar state at the last check
        self.tries: dict[str, int] = {}  # failed renders per replay, this session
        self.retry_at = 0.0  # don't start a render before this (monotonic s)
        self.last_size, self.last_growth = -1, 0.0  # running render's file size, and when it last grew
        self.last_check = 0.0  # when stalled() last ran
        self.last_clips_dir: Path | None = None
        self.capturing = False  # settings window is waiting for a new clip button: don't save replays
        self.raise_settings = threading.Event()
        self.settings_thread: threading.Thread | None = None
        self.jobs_path = jobs_path
        self.jobs_lock = threading.Lock()
        saved = read_json(jobs_path, [])
        # str(Path()) = the same spelling done_job() compares with, whatever slashes another program wrote
        self.jobs: list[str] = ([str(Path(j)) for j in saved if isinstance(j, str) and obs.local_path(j)]
                                if isinstance(saved, list) else [])

    def obs_loop(self) -> None:
        """Stay connected to OBS forever: retry every 5 s while it's closed, reconnect when it comes back."""
        while not self.stop.is_set():
            try:
                self.obs_session()
            except Exception:
                log.exception("OBS connection hit an error, retrying")
                self.conn = None
                self.stop.wait(5)

    def obs_session(self) -> None:
        """One connect attempt, then stay until OBS goes away."""
        ws = obs.websocket_settings()
        port = self.cfg["port"] or ws.get("port", 4455)
        try:
            conn = obs.Obs(self.cfg["host"], port, connection_password(self.cfg, ws), self.on_saved)
        except obs.CONNECT_ERRORS as e:
            log.debug("OBS not reachable on port %s: %s", port, e)
            self.stop.wait(5)
            return
        log.info("Connected to OBS on port %s", port)
        if self.cfg["auto_replay_buffer"]:
            try:
                obs.ensure_replay_buffer(conn)
            except obs.CONNECT_ERRORS as e:
                log.warning("Couldn't start the replay buffer (enable it in OBS: Settings > Output): %s", e)
        self.conn = conn
        while conn.alive and not self.stop.is_set():
            self.stop.wait(1)
        self.conn = None
        conn.close()
        log.info("Disconnected from OBS")

    def on_press(self) -> None:
        if time.monotonic() - self.last_save < SAVE_COOLDOWN:
            log.info("Clip button pressed again within %s s of a save, ignored", SAVE_COOLDOWN)
            return
        conn = self.conn
        if not conn:
            log.warning("Clip button pressed but OBS isn't connected")
            self.beep(ok=False)
            return
        try:
            conn.request("save_replay_buffer")
        except obs.CONNECT_ERRORS as e:
            log.warning("Couldn't save the replay (is the replay buffer running?): %s", e)
            self.beep(ok=False)
            return
        self.last_save = time.monotonic()
        log.info("Clip button pressed, OBS is saving the replay")
        self.beep(ok=True)  # right away, not when OBS finishes writing (~2 s later)

    def beep(self, ok: bool) -> None:
        if not self.cfg["beep"]:
            return
        try:
            if ok:
                winsound.Beep(1200, 90)  # short high: saving
            else:
                winsound.Beep(400, 250)  # longer low: didn't save
        except RuntimeError:
            pass  # no sound device: the save itself still worked

    def on_saved(self, path: Path) -> None:
        if not obs.local_path(path):
            log.warning("Ignoring a replay that isn't on a local drive: %s", path)
            return
        log.info("Replay saved, will render once you're out of the match: %s", path)
        self.last_seen = time.monotonic()  # you just clipped, so you're playing: restart the 60 s wait
        self.last_clips_dir = render.output_path(path).parent
        with self.jobs_lock:
            if str(path) not in self.jobs:
                self.jobs.append(str(path))
                self.save_jobs()

    def done_job(self, path: Path) -> None:
        with self.jobs_lock:
            if str(path) in self.jobs:
                self.jobs.remove(str(path))
                self.save_jobs()

    def save_jobs(self) -> None:
        try:
            write_json(self.jobs_path, self.jobs)
        except OSError as e:  # disk full, antivirus lock: the queue in memory still has everything
            log.error("Couldn't save the clip queue to disk (clips still render this session): %s", e)

    def health_bar_visible(self) -> bool | None:
        """True/False, or None if OBS is connected but didn't answer."""
        conn = self.conn
        if not conn:
            return False  # OBS closed: nothing to protect, render away
        try:
            return visible(conn.screenshot(), clip_box(self.cfg))
        except obs.CONNECT_ERRORS as e:
            log.debug("Screenshot failed: %s", e)
            return None

    def start_next(self) -> render.Job | None:
        src = Path(self.jobs[0])
        if not src.exists():
            log.warning("Replay is gone, skipping: %s", src)
            self.done_job(src)
            return None
        log.info("Out of match: rendering %s", src.name)
        try:
            job = render.start(src, clip_box(self.cfg))
        except (FileNotFoundError, RuntimeError) as e:  # ffmpeg missing or broken: not this clip's fault
            log.error("Couldn't start ffmpeg, trying again in %s s: %s", RETRY_AFTER, e)
            self.retry_at = time.monotonic() + RETRY_AFTER
            return None
        except OSError as e:  # this clip's folder or file: count it, let the others go first
            self.failed(src, str(e))
            return None
        self.last_size, self.last_growth = -1, time.monotonic()
        return job

    def finish(self, job: render.Job) -> None:
        try:
            log.info("Vertical clip ready: %s", render.finish(job))
        except (RuntimeError, OSError) as e:  # ffmpeg failed, or the new file is locked (antivirus, OneDrive)
            self.failed(job.src, str(e))
            return
        self.done_job(job.src)

    def failed(self, src: Path, why: str) -> None:
        """A render didn't work: retry it after the others, give up after MAX_TRIES."""
        key = str(src)
        self.tries[key] = self.tries.get(key, 0) + 1
        if self.tries[key] >= MAX_TRIES:
            log.error("Giving up on %s after %s tries (the replay itself is untouched): %s", src, MAX_TRIES, why)
            self.done_job(src)
            return
        wait = RETRY_AFTER * self.tries[key]  # a fault that hits every clip (disk full) can't burn the queue
        self.retry_at = time.monotonic() + wait
        log.warning("Render failed for %s, trying again in %s s after the other clips: %s", src, wait, why)
        with self.jobs_lock:
            if key in self.jobs:
                self.jobs.remove(key)
                self.jobs.append(key)
                self.save_jobs()

    def stalled(self, now: float) -> bool:
        """True if the running render's file hasn't grown for STALL_AFTER s while not paused (hung ffmpeg)."""
        try:
            size = self.job.part.stat().st_size
        except OSError:
            size = 0
        slept = now - self.last_check > 10 * CHECK_EVERY  # PC asleep: monotonic time ran, ffmpeg didn't
        self.last_check = now
        if self.suspended or size != self.last_size or slept:
            self.last_size, self.last_growth = size, now
            return False
        return now - self.last_growth > STALL_AFTER

    def gate_loop(self) -> None:
        """Render queued replays only while you're out of a match; pause the render if one starts."""
        while not self.stop.wait(CHECK_EVERY):
            try:
                self.gate_step()
            except Exception:
                log.exception("Render gate hit an error, carrying on")
        if self.job and self.job.proc.poll() is not None:
            self.finish(self.job)  # ffmpeg finished just before Quit: keep the clip
        elif self.job:
            render.cancel(self.job)  # stays queued, renders again next start

    def gate_step(self) -> None:
        if self.job is None and not self.jobs:
            return  # nothing to do: no screenshots, zero cost
        seen = self.health_bar_visible()
        if seen is None:  # OBS is there but didn't answer: assume nothing changed
            seen = bool(self.was_visible)
        if seen != self.was_visible:
            log.info("Health bar %s", "on screen: in a match" if seen else f"gone: rendering in {CLEAR_AFTER} s")
            self.was_visible = seen
        if seen:
            self.last_seen = time.monotonic()
        if self.job and self.job.proc.poll() is not None:
            job, self.job, self.suspended = self.job, None, False  # clear first: a failing finish can't jam us
            self.finish(job)
        elif self.job and self.stalled(time.monotonic()):
            job, self.job, self.suspended = self.job, None, False
            try:
                render.cancel(job)
            except OSError as e:
                log.warning("Couldn't clean up the hung render: %s", e)
            self.failed(job.src, f"ffmpeg made no progress for {STALL_AFTER} s")
        clear = time.monotonic() - self.last_seen >= CLEAR_AFTER
        action = decide(clear, self.job is not None, self.suspended, bool(self.jobs))
        if action == "start" and time.monotonic() >= self.retry_at:
            self.job = self.start_next()
        elif action == "suspend":
            render.suspend(self.job)
            self.suspended = True
            log.info("Health bar is back: render paused")
        elif action == "resume":
            render.resume(self.job)
            self.suspended = False
            log.info("Out of match again: render resumed")

    def status(self) -> str:
        parts = ["connected to OBS" if self.conn else "waiting for OBS"]
        if self.job:
            parts.append("rendering (paused: in a match)" if self.suspended else "rendering")
        waiting = len(self.jobs) - (1 if self.job else 0)  # the clip being rendered is still in the queue
        if waiting:
            parts.append(f"{waiting} clip{'s' if waiting != 1 else ''} waiting")
        if not render.has_ffmpeg():
            parts.append("ffmpeg not installed (open Settings)")
        if not self.cfg["clip_key"]:
            parts.append("no clip button set")
        return "ezClipping: " + ", ".join(parts)

    def clips_folder(self) -> Path | None:
        if self.last_clips_dir:
            return self.last_clips_dir
        conn = self.conn
        if conn:
            try:
                folder = conn.request("get_record_directory").record_directory
                if obs.local_path(folder):
                    return Path(folder) / "vertical"
            except obs.CONNECT_ERRORS:
                pass
        return None

    def open_clips_folder(self) -> None:
        folder = self.clips_folder()
        if not folder:
            log.warning("No clips folder yet: open OBS or save a replay first")
            return
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def clip_key(self) -> int | None:
        return None if self.capturing else self.cfg["clip_key"]

    def open_settings(self) -> None:
        if self.settings_thread and self.settings_thread.is_alive():
            self.raise_settings.set()  # already open: bring it to the front
            return
        self.settings_thread = threading.Thread(target=settings.show, args=(self, tray_image(True)), daemon=True)
        self.settings_thread.start()

    def save_settings(self, new: dict) -> None:
        """Write cfg + new to config.json, then use it. OSError if it couldn't be saved (nothing changes then)."""
        if not self.config_path:
            raise OSError("your settings file couldn't be read at startup, so it isn't overwritten. "
                          "Restart ezClipping to try again")
        save_config(self.cfg | new, self.config_path)
        self.cfg.update(new)
        try:
            set_start_with_windows(self.cfg["start_with_windows"])
        except OSError as e:
            log.warning("Settings saved, but Start with Windows couldn't be updated: %s", e)

    def apply_settings(self, new: dict) -> None:
        """Called by the settings window on Save. Everything takes effect right away; OSError if not saved."""
        reconnect = any(new.get(k, self.cfg[k]) != self.cfg[k] for k in ("host", "port", "password"))
        self.save_settings(new)
        conn = self.conn
        if reconnect and conn:
            conn.close()  # obs_loop notices and reconnects with the new settings
        log.info("Settings saved")

    def toggle_start_with_windows(self) -> None:
        try:
            self.save_settings({"start_with_windows": not self.cfg["start_with_windows"]})
        except OSError as e:
            log.error("Couldn't change Start with Windows: %s", e)

    def tray_loop(self, icon: pystray.Icon) -> None:
        icon.visible = True
        shown = None
        while True:
            now = (self.status(), self.conn is not None)
            if now != shown:  # each update is a shell call: only when something changed
                icon.title, icon.icon = now[0][:127], tray_image(now[1])
                shown = now
            if self.stop.wait(2):
                return

    def quit(self, icon: pystray.Icon) -> None:
        log.info("Quitting")
        self.stop.set()
        icon.stop()

    def run(self) -> None:
        gate = threading.Thread(target=self.gate_loop, daemon=True)
        for t in (gate, threading.Thread(target=self.obs_loop, daemon=True),
                  threading.Thread(target=hotkey.watch, args=(self.clip_key, self.on_press, self.stop), daemon=True)):
            t.start()
        if not self.cfg["clip_key"] or not render.has_ffmpeg():
            self.open_settings()  # first run, or ffmpeg missing: nothing works until that's sorted
        menu = pystray.Menu(
            pystray.MenuItem("Settings", self.open_settings),
            pystray.MenuItem("Open clips folder", self.open_clips_folder, default=True),
            pystray.MenuItem("Start with Windows", self.toggle_start_with_windows,
                             checked=lambda item: self.cfg["start_with_windows"]),
            pystray.MenuItem("Quit", self.quit),
        )
        log.info("ezClipping running")
        pystray.Icon("ezClipping", tray_image(False), "ezClipping", menu).run(setup=self.tray_loop)
        self.stop.set()
        gate.join(timeout=10)  # let it stop a running render and delete its half-written file
        if self.settings_thread:
            self.settings_thread.join(timeout=2)  # it closes itself when it sees stop


def main() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [RotatingFileHandler(APP_DIR / "ezclipping.log", maxBytes=1_000_000, backupCount=1)]
    if sys.stderr:  # no console when packaged with --noconsole
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    threading.excepthook = lambda a: log.error("Thread %s crashed", a.thread, exc_info=(a.exc_type, a.exc_value,
                                                                                       a.exc_traceback))
    if not single_instance():
        log.info("ezClipping is already running, not starting a second copy")
        return
    ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp settings window on scaled displays
    cfg = load_config()
    config_path = None if unreadable(CONFIG) else CONFIG
    if config_path is None:
        log.error("Couldn't read %s: using defaults this session and not overwriting it", CONFIG)
    elif CONFIG.exists():  # first run: autostart is written on the first Save, after you've seen the checkbox
        try:
            set_start_with_windows(cfg["start_with_windows"])  # also fixes the path if the exe was moved
        except OSError as e:
            log.warning("Couldn't update Start with Windows: %s", e)
    App(cfg, JOBS, config_path).run()


if __name__ == "__main__":
    main()
