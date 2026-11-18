"""ezClipping: every OBS replay you save becomes a 1080x1920 vertical clip."""

import json
import logging
import os
import queue
import sys
import threading
import time
import winsound
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ezclipping import hotkey, obs, render
from ezclipping.hud import Box, box_for_res

APP_DIR = Path(os.environ.get("APPDATA", "")) / "ezClipping"
CONFIG = APP_DIR / "config.json"
DEFAULTS = {
    "host": "localhost",
    "port": None,  # None = read port/password from OBS's own websocket config on every connect
    "password": None,
    "game_res": [1920, 1080],  # in-game resolution, decides where the health bar is
    "box": None,  # calibrated health-bar box (fractions), overrides game_res
    "clip_key": None,  # Windows virtual-key code of the clip button, e.g. 5 = mouse back button
    "beep": True,  # short sound when a replay is saved
    "auto_replay_buffer": True,  # start OBS's replay buffer when we connect
}
SAVE_COOLDOWN = 5  # s; a second save right after one is the same footage, and a second render
log = logging.getLogger("ezclipping")


def load_config(path: Path = CONFIG) -> dict:
    try:
        return DEFAULTS | json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_config(cfg: dict, path: Path = CONFIG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tmp.replace(path)  # never leave a half-written config behind


def clip_box(cfg: dict) -> Box:
    return tuple(cfg["box"]) if cfg["box"] else box_for_res(*cfg["game_res"])


class App:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.jobs: queue.Queue[Path] = queue.Queue()
        self.stop = threading.Event()
        self.conn: obs.Obs | None = None
        self.last_save = -SAVE_COOLDOWN

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
        log.info("Replay saved: %s", path)
        self.jobs.put(path)

    def render_loop(self) -> None:
        while not self.stop.is_set():
            try:
                src = self.jobs.get(timeout=1)
            except queue.Empty:
                continue
            try:
                log.info("Vertical clip ready: %s", render.render(src, clip_box(self.cfg)))
            except (RuntimeError, OSError) as e:
                log.error("Render failed for %s: %s", src, e)

    def run(self) -> None:
        for loop in (self.obs_loop, self.render_loop):
            threading.Thread(target=loop, daemon=True).start()
        threading.Thread(target=hotkey.watch, args=(lambda: self.cfg["clip_key"], self.on_press, self.stop),
                         daemon=True).start()
        log.info("ezClipping running. Ctrl+C to quit.")
        try:
            while not self.stop.wait(1):  # a bare wait() can't be interrupted by Ctrl+C on Windows
                pass
        except KeyboardInterrupt:
            self.stop.set()


def main() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [RotatingFileHandler(APP_DIR / "ezclipping.log", maxBytes=1_000_000, backupCount=1)]
    if sys.stderr:  # no console when packaged with --noconsole
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    # obsws-python logs the OBS password at INFO and a traceback per failed retry; obs_loop handles both
    for noisy in ("obsws_python", "websocket"):
        logging.getLogger(noisy).setLevel(logging.CRITICAL)
    App(load_config()).run()


if __name__ == "__main__":
    main()
