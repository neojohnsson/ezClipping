import tempfile
import unittest
from pathlib import Path

from ezclipping.__main__ import DEFAULTS, App, decide


class Decide(unittest.TestCase):
    def test_in_match_with_clips_waiting_does_nothing(self):
        self.assertEqual(decide(clear=False, rendering=False, suspended=False, waiting=True), "wait")

    def test_out_of_match_with_clips_waiting_starts_rendering(self):
        self.assertEqual(decide(clear=True, rendering=False, suspended=False, waiting=True), "start")

    def test_out_of_match_with_nothing_waiting_does_nothing(self):
        self.assertEqual(decide(clear=True, rendering=False, suspended=False, waiting=False), "wait")

    def test_match_starts_mid_render_pauses_it(self):
        self.assertEqual(decide(clear=False, rendering=True, suspended=False, waiting=True), "suspend")

    def test_paused_render_stays_paused_while_in_match(self):
        self.assertEqual(decide(clear=False, rendering=True, suspended=True, waiting=True), "wait")

    def test_out_of_match_again_resumes_paused_render(self):
        self.assertEqual(decide(clear=True, rendering=True, suspended=True, waiting=True), "resume")

    def test_running_render_out_of_match_keeps_going(self):
        self.assertEqual(decide(clear=True, rendering=True, suspended=False, waiting=True), "wait")


class Queue(unittest.TestCase):
    def test_saved_replays_survive_a_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp) / "queue.json"
            App(DEFAULTS, jobs_path=jobs).on_saved(Path(tmp) / "Replay 1.mkv")
            self.assertEqual(App(DEFAULTS, jobs_path=jobs).jobs, [str(Path(tmp) / "Replay 1.mkv")])

    def test_finished_job_leaves_the_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp) / "queue.json"
            app = App(DEFAULTS, jobs_path=jobs)
            app.on_saved(Path(tmp) / "Replay 1.mkv")
            app.on_saved(Path(tmp) / "Replay 2.mkv")
            app.done_job(Path(tmp) / "Replay 1.mkv")
            self.assertEqual(App(DEFAULTS, jobs_path=jobs).jobs, [str(Path(tmp) / "Replay 2.mkv")])

    def test_same_replay_is_only_queued_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(DEFAULTS, jobs_path=Path(tmp) / "queue.json")
            app.on_saved(Path(tmp) / "Replay 1.mkv")
            app.on_saved(Path(tmp) / "Replay 1.mkv")
            self.assertEqual(len(app.jobs), 1)

    def test_a_save_restarts_the_out_of_match_timer(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(DEFAULTS, jobs_path=Path(tmp) / "queue.json")
            app.last_seen = 0.0  # health bar not seen for ages
            app.on_saved(Path(tmp) / "Replay 1.mkv")  # but you just clipped, so you're playing
            self.assertGreater(app.last_seen, 0.0)


if __name__ == "__main__":
    unittest.main()
