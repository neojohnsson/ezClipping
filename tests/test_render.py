import ctypes
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from ezclipping import render
from ezclipping.hud import box_for_res


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def make_replay(folder: Path, w: int, h: int, seconds: float) -> Path:
    """Fake OBS replay: left half red, right half blue, green top band, yellow bottom band,
    white rectangle exactly where the health bar box is."""
    img = Image.new("RGB", (w, h), (255, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([w // 2, 0, w, h], fill=(0, 0, 255))
    draw.rectangle([0, 0, w, int(h * 0.03)], fill=(0, 255, 0))
    draw.rectangle([0, int(h * 0.97), w, h], fill=(255, 255, 0))
    bx, by, bw, bh = box_for_res(2200, 1440)
    draw.rectangle([bx * w, by * h, (bx + bw) * w, (by + bh) * h], fill=(255, 255, 255))
    img.save(folder / "src.png")
    replay = folder / "Replay 2026-11-18 20-00-00.mkv"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "180", "-t", str(seconds),
         "-i", str(folder / "src.png"), "-f", "lavfi", "-t", str(seconds), "-i", "sine=f=440",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(replay)],
        check=True,
    )
    return replay


class BoxForRes(unittest.TestCase):
    def test_measured_box_for_stretched_2200x1440(self):
        x, y, w, h = box_for_res(2200, 1440)
        self.assertAlmostEqual(x, 0.0266, places=3)
        self.assertAlmostEqual(y, 0.896, places=3)
        self.assertAlmostEqual(w, 0.200, places=3)
        self.assertAlmostEqual(h, 0.0667, places=3)

    def test_wider_aspect_moves_box_left_and_narrows_it(self):
        x169, _, w169, _ = box_for_res(1920, 1080)
        x, _, w, _ = box_for_res(2200, 1440)
        self.assertLess(x169, x)
        self.assertLess(w169, w)

    def test_same_aspect_gives_same_box(self):
        self.assertEqual(box_for_res(1920, 1080), box_for_res(2560, 1440))


class DetectEncoder(unittest.TestCase):
    def test_skips_unusable_encoder(self):
        self.assertEqual(render.detect_encoder(("not_a_real_encoder", "libx264")), "libx264")

    def test_default_picks_a_known_encoder(self):
        self.assertIn(render.detect_encoder(), render.ENCODERS)


class RenderVertical(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        folder = Path(cls.tmp.name)
        cls.replay = make_replay(folder, 2560, 1440, 2)
        cls.out = render.render(cls.replay, box_for_res(2200, 1440))
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", str(cls.out), "-frames:v", "1",
             str(folder / "frame.png")],
            check=True,
        )
        cls.frame = Image.open(folder / "frame.png").convert("RGB")
        cls.info = probe(cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.frame.close()
        cls.tmp.cleanup()

    def is_color(self, xy, color):
        return all(abs(a - b) < 70 for a, b in zip(self.frame.getpixel(xy), color))

    def test_writes_next_to_replay_in_vertical_folder_without_part_file(self):
        self.assertEqual(self.out, self.replay.parent / "vertical" / f"{self.replay.stem}_vertical.mp4")
        self.assertEqual(list(self.out.parent.glob("*.part*")), [])

    def test_output_is_1080x1920_60fps_h264_aac(self):
        video = next(s for s in self.info["streams"] if s["codec_type"] == "video")
        audio = next(s for s in self.info["streams"] if s["codec_type"] == "audio")
        self.assertEqual((video["width"], video["height"]), (1080, 1920))
        self.assertEqual(video["r_frame_rate"], "60/1")
        self.assertEqual(video["codec_name"], "h264")
        self.assertEqual(audio["codec_name"], "aac")

    def test_same_length_as_replay(self):
        src = float(probe(self.replay)["format"]["duration"])
        self.assertAlmostEqual(float(self.info["format"]["duration"]), src, delta=0.1)

    def test_gameplay_strip_is_center_half_of_frame(self):
        self.assertTrue(self.is_color((270, 960), (255, 0, 0)))  # left of center -> red half
        self.assertTrue(self.is_color((810, 960), (0, 0, 255)))  # right of center -> blue half

    def test_gameplay_strip_spans_y_352_to_1568(self):
        self.assertTrue(self.is_color((270, 362), (0, 255, 0)))  # strip's top band
        self.assertFalse(self.is_color((270, 340), (0, 255, 0)))  # blurred bg above it
        self.assertTrue(self.is_color((270, 1556), (255, 255, 0)))  # strip's bottom band
        self.assertFalse(self.is_color((270, 1585), (255, 255, 0)))  # blurred bg below it

    def test_background_is_the_same_frame_blurred(self):
        self.assertTrue(self.is_color((200, 200), (255, 0, 0)))  # left of center -> red
        self.assertTrue(self.is_color((880, 1750), (0, 0, 255)))  # right of center -> blue

    def test_health_bar_corners_outside_card_shape_show_gameplay(self):
        self.assertTrue(self.is_color((166, 1316), (255, 0, 0)))  # top-left corner of bar box -> strip red

    def test_health_bar_is_756_box_centered_at_72_percent(self):
        white_x = [x for x in range(1080) if self.is_color((x, 1382), (255, 255, 255))]
        # stop above the yellow band: blue/yellow chroma blending makes a near-white row at its edge
        white_y = [y for y in range(1200, 1520) if self.is_color((540, y), (255, 255, 255))]
        self.assertAlmostEqual((white_x[0] + white_x[-1]) / 2, 540, delta=6)
        self.assertAlmostEqual((white_y[0] + white_y[-1]) / 2, 1382, delta=6)
        self.assertTrue(0.88 * 756 < len(white_x) <= 756)  # card's angled ends trim the box a bit


class Preview(unittest.TestCase):
    def test_preview_of_a_screenshot_is_the_real_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_replay(Path(tmp), 2560, 1440, 0.1)
            with Image.open(Path(tmp) / "src.png") as img:
                shot = img.copy()  # don't keep the file open: Windows can't delete the temp dir then
        frame = render.preview(shot, box_for_res(2200, 1440)).convert("RGB")
        self.assertEqual(frame.size, (1080, 1920))
        self.assertTrue(all(abs(c - 255) < 70 for c in frame.getpixel((540, 1382))))  # health bar overlay
        self.assertTrue(all(abs(a - b) < 70 for a, b in zip(frame.getpixel((270, 960)), (255, 0, 0))))  # gameplay


class PauseResumeCancel(unittest.TestCase):
    def test_paused_render_makes_no_progress_then_finishes_after_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = render.start(make_replay(Path(tmp), 2560, 1440, 6), box_for_res(2200, 1440))
            for _ in range(100):  # wait until ffmpeg is really writing, or "no growth" proves nothing
                if job.part.exists() and job.part.stat().st_size > 0:
                    break
                time.sleep(0.02)
            render.suspend(job)
            time.sleep(0.3)  # let any in-flight write land
            size = job.part.stat().st_size
            self.assertGreater(size, 0)
            time.sleep(1.0)
            self.assertEqual(job.part.stat().st_size, size)
            self.assertIsNone(job.proc.poll())  # still alive, just paused
            render.resume(job)
            out = render.finish(job)
            video = next(s for s in probe(out)["streams"] if s["codec_type"] == "video")
            self.assertAlmostEqual(float(probe(out)["format"]["duration"]), 6, delta=0.1)
            self.assertEqual(video["width"], 1080)

    def test_cancel_kills_ffmpeg_and_leaves_no_part_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = render.start(make_replay(Path(tmp), 2560, 1440, 6), box_for_res(2200, 1440))
            time.sleep(0.5)
            render.suspend(job)  # cancel must also work on a paused render (quit while in a match)
            render.cancel(job)
            self.assertIsNotNone(job.proc.poll())
            self.assertFalse(job.part.exists())
            self.assertFalse(job.dst.exists())


def running(pid: int) -> bool:
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


class Orphans(unittest.TestCase):
    def test_ffmpeg_dies_when_ezclipping_is_killed(self):
        # Task Manager "End task" kills only ezClipping; a paused ffmpeg left behind would lock the .part file
        with tempfile.TemporaryDirectory() as tmp:
            replay = make_replay(Path(tmp), 2560, 1440, 3)  # it's paused at once: length only has to outlast that
            script = (
                "import sys, time; from ezclipping import render; from ezclipping.hud import box_for_res; "
                f"job = render.start(r'{replay}', box_for_res(2200, 1440)); render.suspend(job); "
                "print(job.proc.pid, flush=True); time.sleep(60)"
            )
            app = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True,
                                   cwd=Path(__file__).parent.parent)
            ffmpeg_pid = int(app.stdout.readline())
            self.assertTrue(running(ffmpeg_pid))
            app.kill()  # TerminateProcess on ezClipping only, not its children
            app.wait()
            time.sleep(0.5)
            self.assertFalse(running(ffmpeg_pid))


class RenderOddSizes(unittest.TestCase):
    def test_cpu_encoder_renders_a_whole_clip(self):
        # the fallback for PCs without a working NVIDIA/AMD/Intel encoder; this PC always picks NVENC
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(render, "detect_encoder", return_value="libx264"):
            out = render.render(make_replay(Path(tmp), 1920, 1080, 0.5), box_for_res(1920, 1080))
            info = probe(out)
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["codec_name"], video["width"], video["height"]), ("h264", 1080, 1920))
        self.assertAlmostEqual(float(info["format"]["duration"]), 0.5, delta=0.1)

    def test_1080p_source_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = render.render(make_replay(Path(tmp), 1920, 1080, 0.5), box_for_res(1920, 1080))
            video = next(s for s in probe(out)["streams"] if s["codec_type"] == "video")
            self.assertEqual((video["width"], video["height"]), (1080, 1920))


if __name__ == "__main__":
    unittest.main()
