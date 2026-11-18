"""Where the player's own health bar sits on screen."""

Box = tuple[float, float, float, float]


def box_for_res(w: int, h: int) -> Box:
    """Health bar (x, y, w, h) as fractions of the frame, for in-game resolution w x h.

    Apex keeps the HUD a fixed distance from the bottom-left in units of screen height, so x and w shrink
    as the aspect gets wider. Measured on 2200x1440 stretched footage.
    """
    aspect = w / h
    return (0.0406 / aspect, 0.896, 0.3056 / aspect, 0.0667)
