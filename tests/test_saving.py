"""Saving settings must never destroy the user's config, and a failed save must be visible, not silent."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ezclipping.__main__ as main
from ezclipping.__main__ import DEFAULTS, App, clean_config, unreadable


class ApplySettings(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        patcher = mock.patch.object(main, "set_start_with_windows")  # never touch the real Run key
        self.autostart = patcher.start()
        self.addCleanup(patcher.stop)

    def app(self, config_path):
        return App(dict(DEFAULTS), jobs_path=self.dir / "queue.json", config_path=config_path)

    def test_save_writes_the_settings_file(self):
        app = self.app(self.dir / "config.json")
        app.apply_settings({"clip_key": 5})
        self.assertEqual(json.loads((self.dir / "config.json").read_text())["clip_key"], 5)

    def test_settings_file_unreadable_at_startup_is_never_overwritten(self):
        app = self.app(None)  # main() passes None when config.json exists but couldn't be read
        with self.assertRaises(OSError):
            app.apply_settings({"clip_key": 5})
        self.assertIsNone(app.cfg["clip_key"])

    def test_failed_save_raises_and_changes_nothing(self):
        app = self.app(self.dir)  # a folder: the write fails
        with self.assertRaises(OSError):
            app.apply_settings({"clip_key": 5})
        self.assertIsNone(app.cfg["clip_key"])

    def test_registry_failure_still_saves_the_settings(self):
        self.autostart.side_effect = PermissionError("registry locked")
        app = self.app(self.dir / "config.json")
        app.apply_settings({"clip_key": 5})
        self.assertEqual(app.cfg["clip_key"], 5)

    def test_tray_toggle_with_a_failing_save_does_not_crash(self):
        app = self.app(None)
        app.toggle_start_with_windows()


class Unreadable(unittest.TestCase):
    def test_missing_file_is_not_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(unreadable(Path(tmp) / "config.json"))

    def test_normal_file_is_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config.json").write_text("{}")
            self.assertFalse(unreadable(Path(tmp) / "config.json"))

    def test_file_that_cant_be_read_is_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(unreadable(Path(tmp)))  # a folder can't be read as a file, like a locked one


class ConfigValues(unittest.TestCase):
    def test_left_or_right_mouse_from_config_is_refused(self):
        self.assertIsNone(clean_config({"clip_key": 1})["clip_key"])  # you shoot with it
        self.assertIsNone(clean_config({"clip_key": 2})["clip_key"])  # you aim with it


if __name__ == "__main__":
    unittest.main()
