"""Nothing may kill a worker thread: a dead thread means no renders, no pausing, no clip button, no log line."""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import ezclipping.__main__ as main
from ezclipping import hotkey
from ezclipping.__main__ import DEFAULTS, App


def app_in(tmp: str, **cfg) -> App:
    return App(DEFAULTS | {"beep": False} | cfg, jobs_path=Path(tmp) / "queue.json")


class ClosingConn:
    """What OBS looks like in the second after it starts closing: requests fail with a JSON decode error."""

    def screenshot(self):
        raise json.JSONDecodeError("Expecting value", "", 0)

    def request(self, name, *args):
        raise json.JSONDecodeError("Expecting value", "", 0)


class Robustness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_screenshot_from_a_closing_obs_is_unknown_not_a_crash(self):
        app = app_in(self.tmp.name)
        app.conn = ClosingConn()
        self.assertIsNone(app.health_bar_visible())

    def test_failed_screenshot_while_connected_keeps_you_in_the_match(self):
        app = app_in(self.tmp.name)
        app.jobs, app.was_visible, app.last_seen = ["a.mkv"], True, 0.0
        app.conn = ClosingConn()
        app.gate_step()
        self.assertGreater(app.last_seen, 0.0)  # treated as still visible: no render starts mid-match

    def test_gate_keeps_running_after_an_error(self):
        app = app_in(self.tmp.name)
        app.jobs = ["a.mkv"]
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return True

        app.health_bar_visible = flaky
        with mock.patch.object(main, "CHECK_EVERY", 0.01):
            gate = threading.Thread(target=app.gate_loop, daemon=True)
            gate.start()
            time.sleep(0.3)
            app.stop.set()
            gate.join(2)
        self.assertGreater(len(calls), 1)

    def test_bad_host_does_not_kill_the_obs_loop(self):
        app = app_in(self.tmp.name, host="127.0.0.1:4455")  # port typed into the host field
        loop = threading.Thread(target=app.obs_loop, daemon=True)
        loop.start()
        time.sleep(0.5)
        self.assertTrue(loop.is_alive())
        app.stop.set()
        loop.join(2)

    def test_clip_button_keeps_working_after_a_failing_press(self):
        stop, presses = threading.Event(), []
        states = [0, 0x8000, 0, 0x8000, 0]

        def key_state(vk):
            state = states.pop(0)
            if not states:
                stop.set()
            return state

        def on_press():
            presses.append(1)
            if len(presses) == 1:
                raise RuntimeError("boom")

        hotkey.watch(lambda: 5, on_press, stop, key_state=key_state, poll=0)
        self.assertEqual(len(presses), 2)

    def test_no_sound_device_is_harmless(self):
        app = app_in(self.tmp.name, beep=True)
        with mock.patch("winsound.Beep", side_effect=RuntimeError("no sound device")):
            app.beep(ok=True)

    def test_clip_stays_queued_when_the_queue_file_cant_be_written(self):
        app = App(DEFAULTS, jobs_path=Path(self.tmp.name))  # a folder: every write fails
        app.on_saved(Path(self.tmp.name) / "Replay 1.mkv")
        self.assertEqual(app.jobs, [str(Path(self.tmp.name) / "Replay 1.mkv")])


if __name__ == "__main__":
    unittest.main()
