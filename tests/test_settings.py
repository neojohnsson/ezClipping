import unittest

from ezclipping.hotkey import VK_XBUTTON1, VK_XBUTTON2, key_name
from ezclipping.obs import valid_host
from ezclipping.settings import drag_to_box, parse_res


class DragToBox(unittest.TestCase):
    def test_drag_becomes_fractions_of_the_picture(self):
        box = drag_to_box(100, 450, 300, 490, width=1000, height=500)
        self.assertEqual(box, (0.1, 0.9, 0.2, 0.08))

    def test_dragging_up_and_left_gives_the_same_box(self):
        self.assertEqual(drag_to_box(300, 490, 100, 450, 1000, 500), drag_to_box(100, 450, 300, 490, 1000, 500))

    def test_drag_past_the_edge_is_clamped(self):
        self.assertEqual(drag_to_box(-50, 450, 300, 600, 1000, 500), (0.0, 0.9, 0.3, 0.1))

    def test_a_click_or_tiny_drag_is_not_a_box(self):
        self.assertIsNone(drag_to_box(100, 450, 104, 452, 1000, 500))


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


class Host(unittest.TestCase):
    def test_name_or_ip_is_fine(self):
        self.assertTrue(valid_host("localhost"))
        self.assertTrue(valid_host("192.168.1.20"))

    def test_port_scheme_or_spaces_in_host_are_rejected(self):
        for bad in ("127.0.0.1:4455", "ws://localhost", "my pc", ""):
            self.assertFalse(valid_host(bad), bad)

    def test_url_tricks_in_host_are_rejected(self):
        # 'localhost@evil.com' would connect to evil.com while looking like localhost
        for bad in ("localhost@evil.com", "host?x", "host#x", "a%20b", "a\r\nb"):
            self.assertFalse(valid_host(bad), repr(bad))


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
