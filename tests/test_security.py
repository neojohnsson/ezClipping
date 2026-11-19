import logging
import tempfile
import unittest
from pathlib import Path

from ezclipping import obs
from ezclipping.__main__ import DEFAULTS, App, connection_password


class LocalPathsOnly(unittest.TestCase):
    """A path from OBS's websocket or queue.json that points at another machine must never be touched:
    even checking that it exists makes Windows send your login hash to that machine."""

    def test_local_drive_paths_are_fine(self):
        self.assertTrue(obs.local_path(r"C:\Users\me\Videos\Replay 1.mkv"))
        self.assertTrue(obs.local_path("D:/Recordings/Replay 1.mkv"))

    def test_network_and_relative_paths_are_refused(self):
        for bad in (r"\\attacker\share\x.mkv", "//attacker/share/x.mkv", "Replay 1.mkv", r"\\?\UNC\a\b\c.mkv"):
            self.assertFalse(obs.local_path(bad), bad)

    def test_a_network_replay_from_obs_is_not_queued(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(DEFAULTS, jobs_path=Path(tmp) / "queue.json")
            app.on_saved(Path(r"\\attacker\share\Replay 1.mkv"))
            self.assertEqual(app.jobs, [])

    def test_network_paths_in_queue_json_are_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp) / "queue.json"
            queue.write_text('["C:/Videos/a.mkv", "\\\\\\\\attacker\\\\share\\\\b.mkv"]')
            self.assertEqual(App(DEFAULTS, jobs_path=queue).jobs, ["C:/Videos/a.mkv"])


OBS_WS = {"port": 4455, "password": "obs-secret"}  # what OBS's own websocket config holds


class Password(unittest.TestCase):
    def test_obs_password_is_used_for_this_pc(self):
        self.assertEqual(connection_password(DEFAULTS, OBS_WS), "obs-secret")

    def test_obs_password_never_goes_to_another_machine(self):
        self.assertEqual(connection_password(DEFAULTS | {"host": "192.168.1.20"}, OBS_WS), "")

    def test_typed_password_is_used_as_typed(self):
        self.assertEqual(connection_password(DEFAULTS | {"host": "192.168.1.20", "password": "mine"}, OBS_WS),
                         "mine")

    def test_obsws_cannot_log_the_password(self):
        # obsws-python logs connection parameters, password included, at INFO
        self.assertGreaterEqual(logging.getLogger("obsws_python").getEffectiveLevel(), logging.CRITICAL)


if __name__ == "__main__":
    unittest.main()
