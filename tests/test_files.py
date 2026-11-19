"""config.json / queue.json are files other software can touch: survive damage, never lose data, trust nothing."""

import json
import tempfile
import threading
import unittest
from pathlib import Path

from ezclipping import render
from ezclipping.__main__ import DEFAULTS, App, clean_config, load_config, write_json


class Files(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_two_threads_saving_at_once_leave_a_valid_file(self):
        path = self.dir / "config.json"
        errors = []

        def hammer(n):
            try:
                for i in range(100):
                    write_json(path, {"writer": n, "i": i})
            except OSError as e:
                errors.append(e)

        threads = [threading.Thread(target=hammer, args=(n,)) for n in (1, 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertIn(json.loads(path.read_text())["writer"], (1, 2))

    def test_damaged_queue_is_kept_aside_not_overwritten(self):
        queue = self.dir / "queue.json"
        queue.write_text('["C:/Videos/Replay 1.mkv", ')  # cut off mid-write
        app = App(DEFAULTS, jobs_path=queue)
        self.assertEqual(app.jobs, [])
        self.assertEqual((self.dir / "queue.bad.json").read_text(), '["C:/Videos/Replay 1.mkv", ')

    def test_damaged_config_is_kept_aside(self):
        config = self.dir / "config.json"
        config.write_text("{oops")
        self.assertEqual(load_config(config), DEFAULTS)
        self.assertTrue((self.dir / "config.bad.json").exists())

    def test_queue_entries_that_are_not_paths_are_dropped(self):
        queue = self.dir / "queue.json"
        queue.write_text(json.dumps(["C:/Videos/a.mkv", 5, None, {"x": 1}]))
        self.assertEqual(App(DEFAULTS, jobs_path=queue).jobs, [str(Path("C:/Videos/a.mkv"))])

    def test_output_never_overwrites_a_finished_clip(self):
        taken = self.dir / "Replay_vertical.mp4"
        taken.write_bytes(b"finished clip")
        self.assertEqual(render.free_path(taken), self.dir / "Replay_vertical (2).mp4")


class CleanConfig(unittest.TestCase):
    def test_config_that_is_not_an_object_gives_defaults(self):
        self.assertEqual(clean_config([1, 2, 3]), DEFAULTS)

    def test_box_that_is_not_four_fractions_is_ignored(self):
        # a string here would go straight into ffmpeg's -filter_complex
        self.assertIsNone(clean_config({"box": "0.1:0.9,drawtext=text=hi"})["box"])
        self.assertIsNone(clean_config({"box": [0.1, 0.9, 0.5]})["box"])
        self.assertIsNone(clean_config({"box": [0.1, 0.9, 2.0, 0.05]})["box"])

    def test_valid_box_is_kept(self):
        self.assertEqual(clean_config({"box": [0.03, 0.9, 0.2, 0.06]})["box"], [0.03, 0.9, 0.2, 0.06])

    def test_impossible_resolution_falls_back(self):
        self.assertEqual(clean_config({"game_res": [1, 1]})["game_res"], DEFAULTS["game_res"])
        self.assertEqual(clean_config({"game_res": "2200x1440"})["game_res"], DEFAULTS["game_res"])

    def test_bad_clip_key_port_and_host_fall_back(self):
        cfg = clean_config({"clip_key": "abc", "port": 99999, "host": "127.0.0.1:4455", "beep": "yes"})
        self.assertEqual((cfg["clip_key"], cfg["port"], cfg["host"], cfg["beep"]),
                         (DEFAULTS["clip_key"], DEFAULTS["port"], DEFAULTS["host"], DEFAULTS["beep"]))

    def test_good_values_are_kept(self):
        good = {"clip_key": 16, "port": 4466, "host": "localhost", "game_res": [2200, 1440], "password": "pw"}
        self.assertEqual(clean_config(good), DEFAULTS | good)


if __name__ == "__main__":
    unittest.main()
