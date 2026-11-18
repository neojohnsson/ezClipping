"""Clip button: reads the key state ~30x/s. No keyboard/mouse hooks, so no input lag and nothing for
anti-cheat to look at."""

import ctypes
import threading
from collections.abc import Callable

VK_XBUTTON1, VK_XBUTTON2, VK_ESCAPE = 0x05, 0x06, 0x1B  # mouse side buttons: back, forward
POLL = 1 / 30
# Anything but left/right mouse (you shoot and aim with those) can be the clip button
CAPTURABLE = [vk for vk in range(0x04, 0xFF) if vk != VK_ESCAPE]
MOUSE_NAMES = {0x04: "Mouse 3 (middle)", VK_XBUTTON1: "Mouse 4 (back)", VK_XBUTTON2: "Mouse 5 (forward)"}
# keys whose name needs the "extended" flag, or Windows names them after the numpad (Page Down -> "Num 3")
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0xA3, 0xA5}

_user32 = ctypes.WinDLL("user32")
_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetKeyNameTextW.argtypes = [ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int]


def key_state(vk: int) -> int:
    return _user32.GetAsyncKeyState(vk) & 0xFFFF


def key_name(vk: int | None) -> str:
    """'Mouse 4 (back)', 'F8', 'Page Down', ... in the keyboard layout's language."""
    if not vk:
        return "Not set"
    if vk in MOUSE_NAMES:
        return MOUSE_NAMES[vk]
    scan = _user32.MapVirtualKeyW(vk, 0)  # MAPVK_VK_TO_VSC
    buf = ctypes.create_unicode_buffer(64)
    if scan and _user32.GetKeyNameTextW((scan << 16) | ((1 << 24) if vk in EXTENDED else 0), buf, 64):
        return buf.value.title()
    return f"Key {vk:#04x}"


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
