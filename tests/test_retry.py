"""A render that fails or hangs must never silently cost the user a clip, or jam the queue."""

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import ezclipping.__main__ as main
from ezclipping import render
from ezclipping.__main__ import CHECK_EVERY, DEFAULTS, MAX_TRIES, RETRY_AFTER, STALL_AFTER, App


def finished_job(src: Path) -> SimpleNamespace:
    """A job whose ffmpeg has exited."""
    return SimpleNamespace(src=src, part=src.with_suffix(".part.mp4"), proc=SimpleNamespace(poll=lambda: 0))


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

    def test_failed_render_waits_before_the_next_try(self):
        # a fault that hits every clip (disk full) must not burn the whole queue in seconds
        self.fail_once(self.bad)
        self.assertGreaterEqual(self.app.retry_at, time.monotonic() + RETRY_AFTER - 1)

    def test_missing_ffmpeg_keeps_the_clip_and_waits(self):
        Path(self.bad).write_bytes(b"replay")
        with mock.patch.object(render, "start", side_effect=FileNotFoundError("ffmpeg.exe is gone")):
            self.assertIsNone(self.app.start_next())
        self.assertEqual(self.app.jobs, [self.bad, self.good])
        self.assertEqual(self.app.tries.get(self.bad, 0), 0)
        self.assertGreater(self.app.retry_at, time.monotonic())

    def test_clip_that_cant_even_start_counts_a_try_and_unblocks_the_queue(self):
        Path(self.bad).write_bytes(b"replay")
        with mock.patch.object(render, "start", side_effect=PermissionError("can't create its vertical folder")):
            self.assertIsNone(self.app.start_next())
        self.assertEqual(self.app.jobs, [self.good, self.bad])

    def test_missing_replay_is_skipped(self):
        self.assertIsNone(self.app.start_next())  # bad.mkv was never written
        self.assertEqual(self.app.jobs, [self.good])

    def test_rename_failing_after_a_finished_render_does_not_jam_the_gate(self):
        # antivirus / OneDrive holding the new file, or the clip open in a player
        self.app.job = finished_job(Path(self.bad))
        self.app.health_bar_visible = lambda: False
        with mock.patch.object(render, "finish", side_effect=PermissionError("file in use")):
            self.app.gate_step()
            self.app.gate_step()
        self.assertIsNone(self.app.job)
        self.assertIn(self.bad, self.app.jobs)  # kept for another try

    def test_failed_cancel_of_a_hung_render_does_not_jam_the_gate(self):
        self.app.job = SimpleNamespace(src=Path(self.bad), part=self.dir / "x.part.mp4",
                                       proc=SimpleNamespace(poll=lambda: None))
        self.app.health_bar_visible = lambda: False
        with mock.patch.object(self.app, "stalled", return_value=True), \
                mock.patch.object(render, "cancel", side_effect=PermissionError("locked")):
            self.app.gate_step()
        self.assertIsNone(self.app.job)


class QueuePaths(unittest.TestCase):
    def test_slashes_are_normalized_so_a_finished_clip_leaves_the_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp) / "queue.json"
            queue.write_text('["C:/Videos/a.mkv"]')  # another program wrote forward slashes
            app = App(DEFAULTS, jobs_path=queue)
            app.done_job(Path("C:/Videos/a.mkv"))
            self.assertEqual(app.jobs, [])


class Stall(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.part = Path(tmp.name) / "clip_vertical.part.mp4"
        self.part.write_bytes(b"x" * 10)
        self.app = App(DEFAULTS, jobs_path=Path(tmp.name) / "queue.json")
        self.app.job = SimpleNamespace(part=self.part)

    def checks(self, start: float, seconds: float) -> bool:
        """Run the stall check every CHECK_EVERY s like the gate does; the last answer."""
        t, hung = start, False
        while t <= start + seconds:
            hung = self.app.stalled(t)
            t += CHECK_EVERY
        return hung

    def test_render_that_stops_growing_for_5_minutes_is_hung(self):
        self.assertFalse(self.checks(1000.0, STALL_AFTER - 2 * CHECK_EVERY))
        self.assertTrue(self.checks(1000.0 + STALL_AFTER - CHECK_EVERY, 3 * CHECK_EVERY))

    def test_growing_render_is_not_hung(self):
        self.checks(1000.0, STALL_AFTER - CHECK_EVERY)
        self.part.write_bytes(b"x" * 20)
        self.assertFalse(self.checks(1000.0 + STALL_AFTER, 2 * CHECK_EVERY))

    def test_paused_render_is_never_hung(self):
        self.app.suspended = True
        self.assertFalse(self.checks(1000.0, 10 * STALL_AFTER))

    def test_pc_asleep_for_an_hour_is_not_a_hang(self):
        self.app.stalled(1000.0)
        self.assertFalse(self.app.stalled(1000.0 + 3600))  # monotonic time includes sleep


class GateEndToEnd(unittest.TestCase):
    def test_render_starts_out_of_match_pauses_in_one_resumes_and_finishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            replay = Path(tmp) / "Replay 1.mkv"
            replay.write_bytes(b"replay")
            app = App(DEFAULTS, jobs_path=Path(tmp) / "queue.json")
            app.jobs = [str(replay)]
            clock, seen, done, calls = [1000.0], [False], [False], []
            app.last_seen = clock[0]
            app.health_bar_visible = lambda: seen[0]
            job = SimpleNamespace(src=replay, part=Path(tmp) / "x.part.mp4",
                                  proc=SimpleNamespace(poll=lambda: 0 if done[0] else None))

            def step(seconds: float) -> None:
                for _ in range(int(seconds // CHECK_EVERY)):
                    clock[0] += CHECK_EVERY
                    app.gate_step()

            with mock.patch.object(main.time, "monotonic", lambda: clock[0]), \
                    mock.patch.object(render, "start", side_effect=lambda *a: calls.append("start") or job), \
                    mock.patch.object(render, "suspend", side_effect=lambda j: calls.append("suspend")), \
                    mock.patch.object(render, "resume", side_effect=lambda j: calls.append("resume")), \
                    mock.patch.object(render, "finish", side_effect=lambda j: calls.append("finish") or replay):
                step(57)  # health bar gone, but not for 60 s yet
                self.assertEqual(calls, [])
                step(6)
                self.assertEqual(calls, ["start"])
                seen[0] = True  # a match starts
                step(3)
                self.assertEqual(calls, ["start", "suspend"])
                seen[0] = False  # match over
                step(63)
                self.assertEqual(calls, ["start", "suspend", "resume"])
                done[0] = True
                step(3)
            self.assertEqual(calls, ["start", "suspend", "resume", "finish"])
            self.assertEqual(app.jobs, [])
            self.assertIsNone(app.job)


if __name__ == "__main__":
    unittest.main()
