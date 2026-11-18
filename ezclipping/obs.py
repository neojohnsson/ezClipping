"""obs-websocket v5 (built into OBS 28+): connect, save replays, hear about saved replays."""

import json
import os
from collections.abc import Callable
from pathlib import Path

import obsws_python as obsws
from obsws_python.error import OBSSDKError
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


class Obs:
    """One live connection to OBS: a request socket plus an event socket for ReplayBufferSaved."""

    def __init__(self, host: str, port: int, password: str, on_saved: Callable[[Path], None]):
        kw = {"host": host, "port": port, "password": password, "timeout": 3}
        self.req = obsws.ReqClient(**kw)
        self.events = obsws.EventClient(**kw)

        def on_replay_buffer_saved(data):  # obsws-python routes events by this function name
            on_saved(Path(data.saved_replay_path))

        self.events.callback.register(on_replay_buffer_saved)

    @property
    def alive(self) -> bool:
        return self.events.worker.is_alive()  # the event thread exits when OBS closes the socket

    def close(self) -> None:
        for client in (self.req, self.events):
            try:
                client.disconnect()
            except CONNECT_ERRORS:
                pass
