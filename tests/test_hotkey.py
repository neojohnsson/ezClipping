import threading
import unittest

from ezclipping import hotkey
from ezclipping.__main__ import DEFAULTS, SAVE_COOLDOWN, App

DOWN, UP, TAPPED = 0x8000, 0, 0x0001  # GetAsyncKeyState bits: held now / pressed since last poll


def run_watch(states, keys=None):
    """Run hotkey.watch over a scripted sequence of key states, return how many presses fired."""
    states, keys = list(states), list(keys or [hotkey.VK_XBUTTON1] * len(states))
    stop, presses = threading.Event(), []

    def key_state(vk):
        state = states.pop(0)
        if not states:
            stop.set()
        return state

    def get_vk():
        vk = keys.pop(0) if keys else None
        if vk is None and not keys:
            stop.set()
        return vk

    hotkey.watch(get_vk, lambda: presses.append(1), stop, key_state=key_state, poll=0)
    return len(presses)


class Watch(unittest.TestCase):
    def test_one_save_per_press_even_when_held(self):
        self.assertEqual(run_watch([UP, DOWN, DOWN, DOWN, UP, DOWN, UP]), 2)

    def test_quick_tap_between_polls_still_counts(self):
        self.assertEqual(run_watch([UP, TAPPED, UP]), 1)

    def test_no_button_set_means_no_saves(self):
        self.assertEqual(run_watch([], keys=[None, None, None]), 0)

    def test_changed_button_applies_on_next_poll(self):
        # button unset for two polls (no key reads), then set while held: only the next real press counts
        self.assertEqual(run_watch([DOWN, UP, DOWN, UP], keys=[None, None, 5, 5, 5, 5]), 1)

    def test_key_still_held_when_it_becomes_the_clip_button_does_not_save(self):
        # you just picked it in settings and haven't let go yet
        self.assertEqual(run_watch([DOWN, DOWN, DOWN, UP], keys=[None, 5, 5, 5, 5]), 0)


class SavingConn:
    def __init__(self):
        self.saves = 0

    def request(self, name, *args):
        self.saves += name == "save_replay_buffer"


class ClipButton(unittest.TestCase):
    def app(self):
        app = App(DEFAULTS | {"beep": False})
        app.conn = SavingConn()
        return app

    def test_press_saves_replay(self):
        app = self.app()
        app.on_press()
        self.assertEqual(app.conn.saves, 1)

    def test_second_press_right_after_a_save_is_ignored(self):
        app = self.app()
        app.on_press()
        app.on_press()  # e.g. pressed again because the beep didn't come instantly
        self.assertEqual(app.conn.saves, 1)

    def test_press_after_cooldown_saves_again(self):
        app = self.app()
        app.on_press()
        app.last_save -= SAVE_COOLDOWN
        app.on_press()
        self.assertEqual(app.conn.saves, 2)

    def test_press_without_obs_does_not_crash(self):
        app = self.app()
        app.conn = None
        app.on_press()


if __name__ == "__main__":
    unittest.main()
