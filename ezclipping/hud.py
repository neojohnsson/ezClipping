"""Where the player's own health bar sits on screen, and whether it's showing right now."""

import re

from PIL import Image, ImageChops

Box = tuple[float, float, float, float]

WHITE = 170  # min(R, G, B) of the HP bar's white fill
CONTRAST = 80  # the bar must be this much brighter than the card right above and below it
BAR = re.compile(b"[%c-\xff]{3,}" % WHITE)  # >= 3 px of white (about 3% HP at 640 px wide)


def box_for_res(w: int, h: int) -> Box:
    """Health bar (x, y, w, h) as fractions of the frame, for in-game resolution w x h.

    Apex keeps the HUD a fixed distance from the bottom-left in units of screen height, so x and w shrink
    as the aspect gets wider. Measured on 2200x1440 stretched footage.
    """
    aspect = w / h
    return (0.0406 / aspect, 0.896, 0.3056 / aspect, 0.0667)


def visible(img: Image.Image, box: Box) -> bool:
    """True if the player's own HP bar is on screen, i.e. they're alive in a match.

    Looks in the lower half of the box for a white run that is clearly brighter than the rows just above
    and below it: a thin bar on the dark card, not a bright wall or a button. Knocked (orange bleed-out bar),
    spectating, menus and death screens all come out False. Tolerates a box that's a little off.
    """
    W, H = img.size
    x, y, w, h = box
    gap = max(2, round(H * h * 0.15))  # rows from the bar to the dark card around it
    left, right = round(W * (x + 0.25 * w)), round(W * (x + 0.55 * w))
    first, last = round(H * (y + 0.5 * h)), round(H * (y + h))
    top, bottom = max(0, first - gap), min(H, last + gap + 3)
    r, g, b = img.convert("RGB").crop((left, top, right, bottom)).split()
    lum = ImageChops.darker(ImageChops.darker(r, g), b).tobytes()  # min channel: only white is bright
    cols = right - left
    rows = [lum[i * cols:(i + 1) * cols] for i in range(bottom - top)]

    for i in range(first - top, min(last - top + 1, len(rows))):
        # The HP bar starts right after the portrait, so its white run starts inside the zone. A panel
        # border (the lobby's MODE SELECT box) runs straight through the zone's left edge.
        runs = [m.span() for m in BAR.finditer(rows[i]) if m.start() > 0]
        if not runs:
            continue
        a, z = max(runs, key=lambda s: s[1] - s[0])
        level = [sum(row[a:z]) / (z - a) for row in rows]  # brightness of the run's columns, per row
        thick = next((k for k in range(i, len(rows)) if level[k] < WHITE), len(rows)) - i
        if not 2 <= thick <= gap + 2:  # bar is 3-4 px tall at 640 wide; 1 px is a border, more is a block
            continue
        above = min(level[max(0, i - gap):i], default=255)
        below = min(level[i + thick:i + thick + gap + 1], default=255)
        if level[i] - max(above, below) >= CONTRAST:
            return True
    return False
