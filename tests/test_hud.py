import io
import time
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from ezclipping.hud import box_for_res, visible

FIXTURES = Path(__file__).parent / "fixtures"
# Fixtures are the bottom-left corner (x 0-30%, y 80-100%) of 640x360 frames from real 2200x1440 footage,
# stacked vertically, one tile per frame. Cropped so no webcam/chat ends up in the repo, and everything outside
# the pixels visible() reads (cols 49-86, rows 43-65 of each 192x72 tile) blacked out: player names, session id.
CROP = (0.0, 0.8, 0.3, 0.2)


def tiles(name: str) -> list[Image.Image]:
    sheet = Image.open(FIXTURES / name).convert("RGB")
    w, h = sheet.size
    th = round(360 * CROP[3])
    return [sheet.crop((0, y, w, y + th)) for y in range(0, h, th)]


def box_in_tile() -> tuple[float, float, float, float]:
    x, y, w, h = box_for_res(2200, 1440)
    cx, cy, cw, ch = CROP
    return ((x - cx) / cw, (y - cy) / ch, w / cw, h / ch)


class RealFootage(unittest.TestCase):
    def test_every_alive_frame_counts_as_visible(self):
        # BR + Mixtape cards, all shield colors, low HP, bright/dark backgrounds
        missed = [i for i, t in enumerate(tiles("hud_visible.png")) if not visible(t, box_in_tile())]
        self.assertEqual(missed, [], "tile indexes in hud_visible.png marked hidden")

    def test_every_out_of_match_frame_counts_as_hidden(self):
        # lobby, pre-match, legend select, intros, loadout, settings, death recap, kill replay, champion, black.
        # Every false "visible" restarts the 60 s wait, so even a few percent would stop renders.
        wrong = [i for i, t in enumerate(tiles("hud_hidden.png")) if visible(t, box_in_tile())]
        self.assertEqual(wrong, [], "tile indexes in hud_hidden.png marked visible")

    def test_works_on_jpeg_screenshots_like_obs_sends(self):
        def as_jpeg(tile):
            buf = io.BytesIO()
            tile.save(buf, "JPEG", quality=90)
            return Image.open(buf)

        alive_missed = [i for i, t in enumerate(tiles("hud_visible.png")) if not visible(as_jpeg(t), box_in_tile())]
        wrong = [i for i, t in enumerate(tiles("hud_hidden.png")) if visible(as_jpeg(t), box_in_tile())]
        self.assertEqual(alive_missed, [])
        self.assertEqual(wrong, [])

    def test_check_is_fast(self):
        frames = tiles("hud_visible.png")
        start = time.perf_counter()
        for t in frames:
            visible(t, box_in_tile())
        self.assertLess((time.perf_counter() - start) / len(frames), 0.005)


class Synthetic(unittest.TestCase):
    BOX = box_for_res(2200, 1440)

    def test_plain_white_screen_is_not_a_health_bar(self):
        self.assertFalse(visible(Image.new("RGB", (640, 360), "white"), self.BOX))

    def test_black_screen_is_hidden(self):
        self.assertFalse(visible(Image.new("RGB", (640, 360), "black"), self.BOX))

    def test_thin_white_bar_on_dark_panel_is_visible(self):
        img = Image.new("RGB", (640, 360), (40, 40, 40))
        ImageDraw.Draw(img).rectangle([60, 339, 136, 342], fill="white")
        self.assertTrue(visible(img, self.BOX))

    def test_tall_bright_block_like_a_button_is_hidden(self):
        img = Image.new("RGB", (640, 360), (40, 40, 40))
        ImageDraw.Draw(img).rectangle([20, 330, 150, 360], fill="white")
        self.assertFalse(visible(img, self.BOX))


if __name__ == "__main__":
    unittest.main()
