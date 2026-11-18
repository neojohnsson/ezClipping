import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ezclipping import obs
from ezclipping.__main__ import DEFAULTS, clip_box, load_config, save_config
from ezclipping.hud import box_for_res


class WebsocketSettings(unittest.TestCase):
    def test_reads_port_password_and_enabled_from_obs_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({
                "alerts_enabled": False, "auth_required": True, "first_load": False,
                "server_enabled": True, "server_password": "s3cret", "server_port": 4466,
            }))
            self.assertEqual(obs.websocket_settings(path), {"port": 4466, "password": "s3cret", "enabled": True})

    def test_missing_or_broken_file_gives_empty_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken.json"
            broken.write_text("{not json")
            self.assertEqual(obs.websocket_settings(Path(tmp) / "nope.json"), {})
            self.assertEqual(obs.websocket_settings(broken), {})


class FakeConn:
    def __init__(self, active: bool):
        self.active, self.calls = active, []

    def request(self, name, *args):
        self.calls.append(name)
        return SimpleNamespace(output_active=self.active) if name == "get_replay_buffer_status" else None


class EnsureReplayBuffer(unittest.TestCase):
    def test_starts_replay_buffer_when_off(self):
        conn = FakeConn(active=False)
        obs.ensure_replay_buffer(conn)
        self.assertIn("start_replay_buffer", conn.calls)

    def test_leaves_running_replay_buffer_alone(self):
        conn = FakeConn(active=True)
        obs.ensure_replay_buffer(conn)
        self.assertNotIn("start_replay_buffer", conn.calls)


class Config(unittest.TestCase):
    def test_missing_file_gives_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_config(Path(tmp) / "config.json"), DEFAULTS)

    def test_save_then_load_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "config.json"
            cfg = DEFAULTS | {"game_res": [2200, 1440], "password": "pw"}
            save_config(cfg, path)
            self.assertEqual(load_config(path), cfg)

    def test_old_config_gets_new_default_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"game_res": [1728, 1080]}))
            self.assertEqual(load_config(path), DEFAULTS | {"game_res": [1728, 1080]})

    def test_broken_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{oops")
            self.assertEqual(load_config(path), DEFAULTS)


class ClipBox(unittest.TestCase):
    def test_uses_formula_for_game_res_when_not_calibrated(self):
        self.assertEqual(clip_box(DEFAULTS | {"game_res": [2200, 1440]}), box_for_res(2200, 1440))

    def test_calibrated_box_wins(self):
        box = [0.1, 0.8, 0.2, 0.05]
        self.assertEqual(clip_box(DEFAULTS | {"box": box}), tuple(box))


if __name__ == "__main__":
    unittest.main()
