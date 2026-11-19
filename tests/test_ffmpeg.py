"""ffmpeg is installed by the user (winget), not bundled: find a usable one, safely."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ezclipping import render
from ezclipping.hud import box_for_res
from tests.test_render import make_replay, probe

REAL = Path(shutil.which("ffmpeg"))  # the test machine's ffmpeg


class FindFfmpeg(unittest.TestCase):
    def test_finds_a_working_ffmpeg(self):
        self.assertEqual(render.find_ffmpeg([Path(r"C:\nope\ffmpeg.exe"), REAL]), str(REAL))

    def test_something_that_is_not_a_usable_ffmpeg_is_skipped(self):
        # runs fine but can't do what the layout needs (stands in for a broken or pre-7.1 ffmpeg)
        self.assertIsNone(render.find_ffmpeg([Path(sys.executable)]))

    def test_never_picks_up_an_ffmpeg_from_the_current_folder(self):
        # a planted ffmpeg.exe next to wherever ezClipping was started must not be run
        with tempfile.TemporaryDirectory() as tmp:
            planted = Path(tmp) / "ffmpeg.exe"
            planted.write_bytes(b"MZ")
            old = os.getcwd()
            os.chdir(tmp)
            try:
                with mock.patch.dict(os.environ, {"PATH": f".;;relative\\bin;{REAL.parent}"}):
                    found = [p.resolve() for p in render.ffmpeg_candidates()]
            finally:
                os.chdir(old)
        self.assertNotIn(planted.resolve(), found)
        self.assertIn(REAL.resolve(), found)


class InputAllowList(unittest.TestCase):
    def test_mp4_replays_still_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            mkv = make_replay(Path(tmp), 1920, 1080, 0.5)
            mp4 = mkv.with_suffix(".mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(mkv), "-c", "copy", str(mp4)], check=True)
            out = render.render(mp4, box_for_res(1920, 1080))
            self.assertEqual(probe(out)["streams"][0]["height"], 1920)

    def test_a_playlist_is_refused_before_it_is_read(self):
        # A playlist's segments could be \\host\share\x.ts: ffmpeg's file protocol would open that over SMB
        # and hand over the Windows login hash. Only real video containers may be opened at all. (This test's
        # segment is http, which ffmpeg blocks anyway, so even a failing run never touches the network.)
        with tempfile.TemporaryDirectory() as tmp:
            evil = Path(tmp) / "Replay 1.m3u8"
            evil.write_text("#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1:9/x.ts\n#EXT-X-ENDLIST\n")
            with self.assertRaises(RuntimeError) as failure:
                render.render(evil, box_for_res(1920, 1080))
        self.assertIn("Format not on whitelist", str(failure.exception))


if __name__ == "__main__":
    unittest.main()
