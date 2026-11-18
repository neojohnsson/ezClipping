"""ezClipping: every OBS replay you save becomes a 1080x1920 vertical clip."""

import json
import logging
import os
import queue
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ezclipping import obs, render
from ezclipping.hud import Box, box_for_res

APP_DIR = Path(os.environ.get("APPDATA", "")) / "ezClipping"
CONFIG = APP_DIR / "config.json"
DEFAULTS = {
    "host": "localhost",
    "port": None,  # None = read port/password from OBS's own websocket config on every connect
    "password": None,
    "game_res": [1920, 1080],  # in-game resolution, decides where the health bar is
    "box": None,  # calibrated health-bar box (fractions), overrides game_res
}
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


def obs_loop(cfg: dict, jobs: queue.Queue, stop: threading.Event) -> None:
    """Stay connected to OBS forever: retry every 5 s while it's closed, reconnect when it comes back."""
    while not stop.is_set():
        ws = obs.websocket_settings()
        port = cfg["port"] or ws.get("port", 4455)
        password = ws.get("password", "") if cfg["password"] is None else cfg["password"]
        try:
            conn = obs.Obs(cfg["host"], port, password, jobs.put)
        except obs.CONNECT_ERRORS as e:
            log.debug("OBS not reachable on port %s: %s", port, e)
            stop.wait(5)
            continue
        log.info("Connected to OBS on port %s", port)
        while conn.alive and not stop.is_set():
            stop.wait(1)
        conn.close()
        log.info("Disconnected from OBS")


def render_loop(cfg: dict, jobs: queue.Queue, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            src = jobs.get(timeout=1)
        except queue.Empty:
            continue
        log.info("Replay saved: %s", src)
        try:
            log.info("Vertical clip ready: %s", render.render(src, clip_box(cfg)))
        except (RuntimeError, OSError) as e:
            log.error("Render failed for %s: %s", src, e)


def main() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [RotatingFileHandler(APP_DIR / "ezclipping.log", maxBytes=1_000_000, backupCount=1)]
    if sys.stderr:  # no console when packaged with --noconsole
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    # obsws-python logs the OBS password at INFO and a traceback per failed retry; obs_loop handles both
    for noisy in ("obsws_python", "websocket"):
        logging.getLogger(noisy).setLevel(logging.CRITICAL)

    cfg, jobs, stop = load_config(), queue.Queue(), threading.Event()
    threading.Thread(target=obs_loop, args=(cfg, jobs, stop), daemon=True).start()
    threading.Thread(target=render_loop, args=(cfg, jobs, stop), daemon=True).start()
    log.info("ezClipping running. Ctrl+C to quit.")
    try:
        while not stop.wait(1):  # a bare wait() can't be interrupted by Ctrl+C on Windows
            pass
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
