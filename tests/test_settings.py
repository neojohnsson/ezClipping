import unittest

from ezclipping.hotkey import VK_XBUTTON1, VK_XBUTTON2, key_name
from ezclipping.settings import parse_res


class ParseRes(unittest.TestCase):
    def test_plain_width_x_height(self):
        self.assertEqual(parse_res("2200x1440"), (2200, 1440))

    def test_spaces_and_capital_x(self):
        self.assertEqual(parse_res("  1728 X 1080 "), (1728, 1080))

    def test_apex_launch_options(self):
        self.assertEqual(parse_res("-w 2200 -h 1440"), (2200, 1440))

    def test_garbage_is_rejected(self):
        self.assertIsNone(parse_res("abc"))

    def test_impossible_sizes_are_rejected(self):
        self.assertIsNone(parse_res("10 x 10"))
        self.assertIsNone(parse_res("1440 x 2560"))  # portrait is not an Apex resolution


class KeyName(unittest.TestCase):
    def test_mouse_side_buttons_have_readable_names(self):
        self.assertEqual(key_name(VK_XBUTTON1), "Mouse 4 (back)")
        self.assertEqual(key_name(VK_XBUTTON2), "Mouse 5 (forward)")

    def test_function_key(self):
        self.assertEqual(key_name(0x77), "F8")

    def test_nothing_set(self):
        self.assertEqual(key_name(None), "Not set")


if __name__ == "__main__":
    unittest.main()
