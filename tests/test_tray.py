import tempfile
import unittest
import uuid
import winreg
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ezclipping import render
from ezclipping.__main__ import (
    DEFAULTS,
    App,
    set_start_with_windows,
    single_instance,
    starts_with_windows,
    startup_command,
)

TEST_RUN_KEY = r"Software\ezClipping-tests\Run"  # never the real Run key


class Status(unittest.TestCase):
    def app(self, **cfg):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return App(DEFAULTS | {"clip_key": 5} | cfg, jobs_path=Path(tmp.name) / "queue.json")

    def test_waiting_for_obs(self):
        self.assertEqual(self.app().status(), "ezClipping: waiting for OBS")

    def test_connected_with_clips_waiting(self):
        app = self.app()
        app.conn = object()
        app.jobs = ["a.mkv", "b.mkv"]
        self.assertEqual(app.status(), "ezClipping: connected to OBS, 2 clips waiting")

    def test_paused_render_does_not_count_itself_as_waiting(self):
        app = self.app()
        app.conn = object()
        app.jobs = ["a.mkv", "b.mkv"]
        app.job, app.suspended = SimpleNamespace(), True
        self.assertEqual(app.status(), "ezClipping: connected to OBS, rendering (paused: in a match), 1 clip waiting")

    def test_tells_you_when_ffmpeg_is_missing(self):
        with mock.patch.object(render, "has_ffmpeg", return_value=False):
            self.assertEqual(self.app().status(), "ezClipping: waiting for OBS, ffmpeg not installed (open Settings)")

    def test_tells_new_users_to_set_a_clip_button(self):
        self.assertEqual(self.app(clip_key=None).status(), "ezClipping: waiting for OBS, no clip button set")


class StartWithWindows(unittest.TestCase):
    def tearDown(self):
        for key in (TEST_RUN_KEY, r"Software\ezClipping-tests"):  # DeleteKey only removes empty keys
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)

    def test_turning_on_registers_the_command(self):
        set_start_with_windows(True, key=TEST_RUN_KEY)
        self.assertTrue(starts_with_windows(key=TEST_RUN_KEY))
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEST_RUN_KEY) as k:
            self.assertEqual(winreg.QueryValueEx(k, "ezClipping")[0], startup_command())

    def test_turning_off_removes_it(self):
        set_start_with_windows(True, key=TEST_RUN_KEY)
        set_start_with_windows(False, key=TEST_RUN_KEY)
        self.assertFalse(starts_with_windows(key=TEST_RUN_KEY))

    def test_turning_off_when_never_on_is_fine(self):
        set_start_with_windows(False, key=TEST_RUN_KEY)
        self.assertFalse(starts_with_windows(key=TEST_RUN_KEY))


class SingleInstance(unittest.TestCase):
    def test_second_copy_is_refused(self):
        name = f"ezClipping-test-{uuid.uuid4()}"
        self.assertTrue(single_instance(name))
        self.assertFalse(single_instance(name))


if __name__ == "__main__":
    unittest.main()
