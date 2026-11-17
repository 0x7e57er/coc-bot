"""Game space: the screen as the bot sees it, for any screen resolution.

Templates, click points and read regions are measured on a 1920x1080 base screen. Clash of
Clans scales its interface uniformly (by the smaller of width/1920 and height/1080) and pins
buttons to the screen edges, while the village stays centred. So the bot:

  1. scales the screenshot uniformly so it is 1080 tall (or 1920 wide),
     giving a game space of e.g. 1920x1080 (16:9) or 1920x1200 (16:10);
  2. moves edge-pinned coordinates by the extra width/height: things in the left
     third stay, the right third moves right, the middle moves half;
  3. keeps battlefield points (deploy positions) centred.

Clash of Clans on Android (BlueStacks) draws its interface 1.2x bigger than the PC pictures the
templates were taken from, at any resolution or DPI. The device's `ui_scale` shrinks the picture by
that much first, so a 1920x1080 BlueStacks screen becomes a 1600x900 game space in which the
pictures fit. The village does not grow as much, so battlefield points and lengths are scaled by
the device's `field_scale` (the village at full zoom-out in game space, relative to the PC's).
Full-screen windows are shrunk to fit the screen instead, each kind its own way: on BlueStacks the
army screen is the PC picture x0.928 around the screen centre (4 px higher), the battle results
x0.833 (pixel for pixel the PC's on the screen). The device lists them in `windows`.
"""

import logging

log = logging.getLogger("bot")

BASE = (1920, 1080)          # the screen the templates, points and regions were measured on


class Space:
    def __init__(self):
        self.native = None          # (w, h) of the screen in its own pixels
        self._for = None            # (w, h, ui_scale, field_scale) the mapping was made for
        self.scale = 1.0            # screen pixels per game-space pixel
        self.field = 1.0            # battlefield size in game space relative to the base screen
        # full-screen windows: (size in game space relative to the base screen, how far their centre is
        # below the screen centre); the first one is the army screen's
        self.windows = ((1.0, 0),)
        self.w, self.h = BASE

    @property
    def base(self):
        return BASE

    def update(self, native_w, native_h, ui_scale=1.0, field_scale=1.0, windows=((1.0, 0),)):
        bw, bh = self.base
        s = min(native_w / bw, native_h / bh) * ui_scale
        w, h = round(native_w / s), round(native_h / s)
        if (native_w, native_h, ui_scale, field_scale) != self._for:
            self._for = (native_w, native_h, ui_scale, field_scale)
            self.native = (native_w, native_h)
            self.scale, self.w, self.h, self.field = s, w, h, field_scale
            self.windows = tuple(windows)
            log.info("Screen %dx%d (aspect %.2f, interface x%.2f, village x%.2f) -> game space %dx%d, "
                     "scale %.3f", native_w, native_h, native_w / native_h, ui_scale, field_scale, w, h, s)
        return w, h

    @property
    def dx(self):
        return self.w - self.base[0]

    @property
    def dy(self):
        return self.h - self.base[1]

    def s(self, length):
        """A length measured on the base screen (button size, offset from a button) in game space.
        The interface is drawn at the base size, so lengths do not change."""
        return int(round(length))

    # --- base -> game space ----------------------------------------------------------
    def _ax(self, x, ref=None):
        ref = x if ref is None else ref
        bw = self.base[0]
        if ref < bw / 3:
            return x
        if ref > 2 * bw / 3:
            return x + self.dx
        return x + self.dx / 2

    def _ay(self, y, ref=None):
        ref = y if ref is None else ref
        bh = self.base[1]
        if ref < bh / 3:
            return y
        if ref > 2 * bh / 3:
            return y + self.dy
        return y + self.dy / 2

    def point(self, x, y):
        """A UI point measured on the base screen, pinned to its nearest edge."""
        return round(self._ax(x)), round(self._ay(y))

    def region(self, x, y, w, h):
        """A UI region measured on the base screen, pinned by its centre."""
        cx, cy = x + w / 2, y + h / 2
        return round(self._ax(x, cx)), round(self._ay(y, cy)), int(w), int(h)

    NEAR = 60       # an element this close to the line between two thirds can be pinned either way

    def search_region(self, x, y, w, h):
        """Where to look for a template whose region is (x, y, w, h) on the base screen: pinned by its
        centre, and - when the centre is near the line between two thirds of the screen - also where the
        other third would put it (BlueStacks' "Find a Match" moves like the middle, the PC's sits low)."""
        cx, cy = x + w / 2, y + h / 2
        xs = {self._ax(x, r) for r in (cx - self.NEAR, cx, cx + self.NEAR)}
        ys = {self._ay(y, r) for r in (cy - self.NEAR, cy, cy + self.NEAR)}
        x0, y0 = min(xs), min(ys)
        return round(x0), round(y0), int(max(xs) - x0 + w), int(max(ys) - y0 + h)

    def center(self, x, y):
        """A battlefield/village point: stays centred (and scaled with the battlefield)."""
        bw, bh = self.base
        return round(self.w / 2 + (x - bw / 2) * self.field), round(self.h / 2 + (y - bh / 2) * self.field)

    def f(self, length):
        """A battlefield length measured on the base screen at full zoom-out, in game space."""
        return length * self.field

    def window_point(self, x, y, window=None):
        """A point of a full-screen window measured on the base screen; `window` is one of self.windows
        (default the army screen's)."""
        k, dy = window or self.windows[0]
        bw, bh = self.base
        return round(self.w / 2 + (x - bw / 2) * k), round(self.h / 2 + dy + (y - bh / 2) * k)

    def window_region(self, x, y, w, h, window=None):
        """A region of a full-screen window measured on the base screen."""
        k = (window or self.windows[0])[0]
        x0, y0 = self.window_point(x, y, window)
        return x0, y0, int(round(w * k)), int(round(h * k))


space = Space()
