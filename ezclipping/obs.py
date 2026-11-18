"""obs-websocket v5 (built into OBS 28+): connect, save replays, hear about saved replays."""

import base64
import io
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path

import obsws_python as obsws
from obsws_python.error import OBSSDKError
from PIL import Image
from websocket import WebSocketException

WS_CONFIG = Path(os.environ.get("APPDATA", "")) / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"
CONNECT_ERRORS = (OSError, OBSSDKError, WebSocketException)  # OBS closed, wrong password, dropped socket


def websocket_settings(path: Path = WS_CONFIG) -> dict:
    """Port, password and enabled flag from OBS's own websocket config, {} if it can't be read."""
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        "port": cfg.get("server_port", 4455),
        "password": cfg.get("server_password", ""),
        "enabled": cfg.get("server_enabled", False),
    }


def ensure_replay_buffer(conn) -> None:
    """Start OBS's replay buffer if it's off. Raises OBSSDKError if it's disabled in OBS's output settings."""
    if not conn.request("get_replay_buffer_status").output_active:
        conn.request("start_replay_buffer")


class Obs:
    """One live connection to OBS: a request socket plus an event socket for ReplayBufferSaved."""

    def __init__(self, host: str, port: int, password: str, on_saved: Callable[[Path], None]):
        kw = {"host": host, "port": port, "password": password, "timeout": 3}
        self.req = obsws.ReqClient(**kw)
        self.lock = threading.Lock()
        video = self.request("get_video_settings")
        self.canvas = (video.base_width, video.base_height)
        self.events = obsws.EventClient(**kw)

        def on_replay_buffer_saved(data):  # obsws-python routes events by this function name
            on_saved(Path(data.saved_replay_path))

        self.events.callback.register(on_replay_buffer_saved)

    def request(self, name: str, *args):
        """One obs-websocket request, e.g. request("save_replay_buffer"). Locked: threads share the socket."""
        with self.lock:
            return getattr(self.req, name)(*args)

    def screenshot(self, width: int = 640) -> Image.Image:
        """Small JPEG of what OBS is outputting right now. Costs OBS ~10 ms of CPU (PNG is ~8x more)."""
        scene = self.request("get_current_program_scene").current_program_scene_name
        height = round(width * self.canvas[1] / self.canvas[0])  # OBS stretches to exactly what we ask
        shot = self.request("get_source_screenshot", scene, "jpg", width, height, 90)
        return Image.open(io.BytesIO(base64.b64decode(shot.image_data.split(",", 1)[1])))

    @property
    def alive(self) -> bool:
        return self.events.worker.is_alive()  # the event thread exits when OBS closes the socket

    def close(self) -> None:
        for client in (self.req, self.events):
            try:
                client.disconnect()
            except CONNECT_ERRORS:
                pass
