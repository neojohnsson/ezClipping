"""Clip button: reads the key state ~30x/s. No keyboard/mouse hooks, so no input lag and nothing for
anti-cheat to look at."""

import ctypes
import threading
from collections.abc import Callable

VK_XBUTTON1, VK_XBUTTON2 = 0x05, 0x06  # mouse side buttons: back, forward
POLL = 1 / 30

_user32 = ctypes.windll.user32
_user32.GetAsyncKeyState.restype = ctypes.c_short


def key_state(vk: int) -> int:
    return _user32.GetAsyncKeyState(vk) & 0xFFFF


def watch(get_vk: Callable[[], int | None], on_press: Callable[[], None], stop: threading.Event,
          key_state: Callable[[int], int] = key_state, poll: float = POLL) -> None:
    """Call on_press once per press of the button get_vk() names (read every poll, so changes apply live)."""
    was_down = False
    while not stop.wait(poll):
        vk = get_vk()
        state = key_state(vk) if vk else 0
        if state & 0x8001 and not was_down:  # 0x8000 = held now, 0x0001 = tapped since the last poll
            on_press()
        was_down = bool(state & 0x8000)
