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

from ezclipping import hotkey, obs, render
from ezclipping.hud import Box, box_for_res, visible

APP_DIR = Path(os.environ.get("APPDATA", "")) / "ezClipping"
CONFIG = APP_DIR / "config.json"
JOBS = APP_DIR / "queue.json"  # replays waiting to be rendered, survives restarts
CHECK_EVERY = 3  # s between health-bar checks (only while clips are waiting)
CLEAR_AFTER = 60  # s without your health bar on screen before rendering starts
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


def load_config(path: Path = CONFIG) -> dict:
    try:
        return DEFAULTS | json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULTS)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)  # never leave a half-written file behind


def save_config(cfg: dict, path: Path = CONFIG) -> None:
    write_json(path, cfg)


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
    def __init__(self, cfg: dict, jobs_path: Path = JOBS):
        self.cfg = cfg
        self.stop = threading.Event()
        self.conn: obs.Obs | None = None
        self.last_save = -SAVE_COOLDOWN
        self.last_seen = time.monotonic()  # when your health bar was last on screen
        self.job: render.Job | None = None  # the render in progress
        self.suspended = False
        self.last_clips_dir: Path | None = None
        self.jobs_path = jobs_path
        self.jobs_lock = threading.Lock()
        try:
            self.jobs: list[str] = json.loads(jobs_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.jobs = []

    def obs_loop(self) -> None:
        """Stay connected to OBS forever: retry every 5 s while it's closed, reconnect when it comes back."""
        while not self.stop.is_set():
            ws = obs.websocket_settings()
            port = self.cfg["port"] or ws.get("port", 4455)
            password = ws.get("password", "") if self.cfg["password"] is None else self.cfg["password"]
            try:
                conn = obs.Obs(self.cfg["host"], port, password, self.on_saved)
            except obs.CONNECT_ERRORS as e:
                log.debug("OBS not reachable on port %s: %s", port, e)
                self.stop.wait(5)
                continue
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
        if ok:
            winsound.Beep(1200, 90)  # short high: saving
        else:
            winsound.Beep(400, 250)  # longer low: didn't save

    def on_saved(self, path: Path) -> None:
        log.info("Replay saved, will render once you're out of the match: %s", path)
        self.last_seen = time.monotonic()  # you just clipped, so you're playing: restart the 60 s wait
        self.last_clips_dir = render.output_path(path).parent
        with self.jobs_lock:
            if str(path) not in self.jobs:
                self.jobs.append(str(path))
                write_json(self.jobs_path, self.jobs)

    def done_job(self, path: Path) -> None:
        with self.jobs_lock:
            if str(path) in self.jobs:
                self.jobs.remove(str(path))
                write_json(self.jobs_path, self.jobs)

    def health_bar_visible(self) -> bool:
        conn = self.conn
        if not conn:
            return False  # OBS closed: nothing to protect, render away
        try:
            return visible(conn.screenshot(), clip_box(self.cfg))
        except obs.CONNECT_ERRORS as e:
            log.debug("Screenshot failed: %s", e)
            return False

    def start_next(self) -> render.Job | None:
        src = Path(self.jobs[0])
        if not src.exists():
            log.warning("Replay is gone, skipping: %s", src)
            self.done_job(src)
            return None
        log.info("Out of match: rendering %s", src.name)
        try:
            return render.start(src, clip_box(self.cfg))
        except (RuntimeError, OSError) as e:
            log.error("Couldn't start rendering %s: %s", src, e)
            self.done_job(src)
            return None

    def finish(self, job: render.Job) -> None:
        try:
            log.info("Vertical clip ready: %s", render.finish(job))
        except RuntimeError as e:
            log.error("Render failed for %s (the replay itself is untouched): %s", job.src, e)
        self.done_job(job.src)

    def gate_loop(self) -> None:
        """Render queued replays only while you're out of a match; pause the render if one starts."""
        was_visible = None
        while not self.stop.wait(CHECK_EVERY):
            if self.job is None and not self.jobs:
                continue  # nothing to do: no screenshots, zero cost
            seen = self.health_bar_visible()
            if seen != was_visible:
                log.info("Health bar %s", "on screen: in a match" if seen else f"gone: rendering in {CLEAR_AFTER} s")
                was_visible = seen
            if seen:
                self.last_seen = time.monotonic()
            if self.job and self.job.proc.poll() is not None:
                self.finish(self.job)
                self.job, self.suspended = None, False
            clear = time.monotonic() - self.last_seen >= CLEAR_AFTER
            action = decide(clear, self.job is not None, self.suspended, bool(self.jobs))
            if action == "start":
                self.job = self.start_next()
            elif action == "suspend":
                render.suspend(self.job)
                self.suspended = True
                log.info("Health bar is back: render paused")
            elif action == "resume":
                render.resume(self.job)
                self.suspended = False
                log.info("Out of match again: render resumed")
        if self.job:
            render.cancel(self.job)  # stays queued, renders again next start

    def status(self) -> str:
        parts = ["connected to OBS" if self.conn else "waiting for OBS"]
        if self.job:
            parts.append("rendering (paused: in a match)" if self.suspended else "rendering")
        waiting = len(self.jobs) - (1 if self.job else 0)  # the clip being rendered is still in the queue
        if waiting:
            parts.append(f"{waiting} clip{'s' if waiting != 1 else ''} waiting")
        if not self.cfg["clip_key"]:
            parts.append("no clip button set")
        return "ezClipping: " + ", ".join(parts)

    def clips_folder(self) -> Path | None:
        if self.last_clips_dir:
            return self.last_clips_dir
        conn = self.conn
        if conn:
            try:
                return Path(conn.request("get_record_directory").record_directory) / "vertical"
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

    def toggle_start_with_windows(self) -> None:
        self.cfg["start_with_windows"] = not self.cfg["start_with_windows"]
        save_config(self.cfg)
        set_start_with_windows(self.cfg["start_with_windows"])

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
                  threading.Thread(target=hotkey.watch, args=(lambda: self.cfg["clip_key"], self.on_press, self.stop),
                                   daemon=True)):
            t.start()
        menu = pystray.Menu(
            pystray.MenuItem("Open clips folder", self.open_clips_folder, default=True),
            pystray.MenuItem("Start with Windows", self.toggle_start_with_windows,
                             checked=lambda item: self.cfg["start_with_windows"]),
            pystray.MenuItem("Quit", self.quit),
        )
        log.info("ezClipping running")
        pystray.Icon("ezClipping", tray_image(False), "ezClipping", menu).run(setup=self.tray_loop)
        self.stop.set()
        gate.join(timeout=10)  # let it stop a running render and delete its half-written file


def main() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [RotatingFileHandler(APP_DIR / "ezclipping.log", maxBytes=1_000_000, backupCount=1)]
    if sys.stderr:  # no console when packaged with --noconsole
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    # obsws-python logs the OBS password at INFO and a traceback per failed retry; obs_loop handles both
    for noisy in ("obsws_python", "websocket"):
        logging.getLogger(noisy).setLevel(logging.CRITICAL)
    if not single_instance():
        log.info("ezClipping is already running, not starting a second copy")
        return
    cfg = load_config()
    set_start_with_windows(cfg["start_with_windows"])  # also fixes the path if the exe was moved
    App(cfg).run()


if __name__ == "__main__":
    main()
