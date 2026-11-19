"""ffmpeg is installed by the user (winget), not bundled: find a usable one, safely."""

import os
import shutil
import subprocess
import sys
import tempfile
import time
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

    def test_no_localappdata_does_not_make_winget_paths_relative(self):
        # LOCALAPPDATA unset -> "Microsoft\WinGet\Links\ffmpeg.exe", which Windows resolves in the current folder
        with tempfile.TemporaryDirectory() as tmp:
            planted = Path(tmp, "Microsoft", "WinGet", "Links", "ffmpeg.exe")
            planted.parent.mkdir(parents=True)
            planted.write_bytes(b"MZ")
            old = os.getcwd()
            os.chdir(tmp)
            try:
                with mock.patch.dict(os.environ, {"PATH": str(REAL.parent), "LOCALAPPDATA": ""}), \
                        mock.patch.object(render, "usable", return_value=False) as usable:
                    render.find_ffmpeg()
            finally:
                os.chdir(old)
        ran = [call.args[0] for call in usable.call_args_list]
        self.assertTrue(ran, "the real ffmpeg on PATH should still be tried")
        self.assertTrue(all(exe.is_absolute() for exe in ran), ran)

    def test_an_ffmpeg_that_went_away_is_looked_for_again(self):
        # winget upgrade/uninstall while running: the cached path is gone, so clips would never render
        with mock.patch.dict(render._found, {"path": r"C:\gone\ffmpeg.exe", "at": time.monotonic()}), \
                mock.patch.object(render, "find_ffmpeg", return_value=str(REAL)):
            self.assertEqual(render.ffmpeg(), str(REAL))


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
