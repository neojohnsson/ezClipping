"""A render that fails or hangs must never silently cost the user a clip."""

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ezclipping import render
from ezclipping.__main__ import DEFAULTS, MAX_TRIES, STALL_AFTER, App


class Retry(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.app = App(DEFAULTS | {"beep": False}, jobs_path=self.dir / "queue.json")
        self.bad, self.good = str(self.dir / "bad.mkv"), str(self.dir / "good.mkv")
        self.app.jobs = [self.bad, self.good]

    def fail_once(self, src: str) -> None:
        with mock.patch.object(render, "finish", side_effect=RuntimeError("ffmpeg exited 1")):
            self.app.finish(SimpleNamespace(src=Path(src)))

    def test_failed_render_goes_to_the_back_of_the_queue(self):
        self.fail_once(self.bad)
        self.assertEqual(self.app.jobs, [self.good, self.bad])

    def test_gives_up_only_after_three_failed_renders(self):
        for _ in range(MAX_TRIES - 1):
            self.fail_once(self.bad)
        self.assertIn(self.bad, self.app.jobs)
        self.fail_once(self.bad)
        self.assertEqual(self.app.jobs, [self.good])

    def test_ffmpeg_failing_to_start_keeps_the_clip_and_waits(self):
        Path(self.bad).write_bytes(b"replay")
        with mock.patch.object(render, "start", side_effect=OSError("ffmpeg.exe is gone")):
            self.assertIsNone(self.app.start_next())
        self.assertEqual(self.app.jobs, [self.bad, self.good])
        self.assertGreater(self.app.retry_at, time.monotonic())

    def test_missing_replay_is_skipped(self):
        self.assertIsNone(self.app.start_next())  # bad.mkv was never written
        self.assertEqual(self.app.jobs, [self.good])


class Stall(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.part = Path(tmp.name) / "clip_vertical.part.mp4"
        self.part.write_bytes(b"x" * 10)
        self.app = App(DEFAULTS, jobs_path=Path(tmp.name) / "queue.json")
        self.app.job = SimpleNamespace(part=self.part)

    def test_render_that_stops_growing_for_5_minutes_is_hung(self):
        self.assertFalse(self.app.stalled(1000.0))
        self.assertFalse(self.app.stalled(1000.0 + STALL_AFTER - 1))
        self.assertTrue(self.app.stalled(1000.0 + STALL_AFTER + 1))

    def test_growing_render_is_not_hung(self):
        self.app.stalled(1000.0)
        self.part.write_bytes(b"x" * 20)
        self.assertFalse(self.app.stalled(1000.0 + STALL_AFTER + 1))

    def test_paused_render_is_never_hung(self):
        self.app.suspended = True
        self.app.stalled(1000.0)
        self.assertFalse(self.app.stalled(1000.0 + 10 * STALL_AFTER))


if __name__ == "__main__":
    unittest.main()
