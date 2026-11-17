"""The bot context: one object every action works with.

It wraps the device with Stop/Pause checks and gives "wait for this screen" helpers that
always time out (no endless loops).
"""

import logging
import os
import random
import time
from datetime import datetime

import cv2

from . import layout, paths, vision
from .control import control

log = logging.getLogger("bot")


class BotError(Exception):
    """Something went wrong that the bot can recover from (usually by going home)."""


class Bot:
    def __init__(self, device, settings, accounts):
        self.device = device
        self.settings = settings
        self.accounts = accounts
        self.layout = layout
        self.frame = None
        self.current_account = None
        self.current_acc = None          # the account dict we switched to (to reopen it after a reload)
        self.state = {}                  # remembered between runs (config/state.json)
        self.reloaded = False            # the game's Reload / Try Again was tapped: check the account
        self.reload_at = 0.0
        self.stats = {"attacks": 0, "raids": 0, "searches": 0, "requests": 0, "donated": 0, "upgrades": 0, "walls": 0,
                      "loot": {"gold": 0, "elixir": 0, "dark": 0}}
        # for the window: what the bot is doing, each account's last reading and result, the last base's loot,
        # the account # the run is at (the next run goes on from there)
        self.action_at = time.monotonic()  # when the step began (the run's watchdog looks at it)
        self.action = "Starting"
        self.progress = {}               # account name -> {"status", "res", "raids", "left"}
        self.last_loot = None
        self.start_from = 1

    @property
    def action(self):
        """What the bot is doing now (shown in the window). Each new step is logged ("Step: ...") and timed."""
        return self._action

    @action.setter
    def action(self, text):
        if text != getattr(self, "_action", None):
            log.debug("Step: %s", text)
            self.action_at = time.monotonic()
        self._action = text

    # --- screen ----------------------------------------------------------------------------
    def shot(self):
        control.checkpoint()
        self.frame = self.device.capture()
        return self.frame

    def find(self, key, fresh=True, **kw):
        if not vision.templates.has(key):
            return None
        frame = self.shot() if fresh or self.frame is None else self.frame
        return vision.find(frame, key, **kw)

    def exists(self, key, fresh=True, **kw):
        return self.find(key, fresh=fresh, **kw) is not None

    def wait_any(self, keys, timeout=15.0, interval=0.3):
        """Wait until one of the templates appears. Returns (key, match) or (None, None)."""
        keys = [k for k in ([keys] if isinstance(keys, str) else keys) if vision.templates.has(k)]
        end = time.monotonic() + timeout
        tutorials = 0
        while True:
            frame = self.shot()
            for k in keys:
                m = vision.find(frame, k)
                if m:
                    return k, m
            # a tutorial of the game dims the screen: what we wait for is there but grey
            if tutorials < 3 and vision.templates.has("popup/speech_corner") and \
                    "popup/speech_corner" not in keys:
                from .states import dismiss_tutorial
                if dismiss_tutorial(self, frame):
                    tutorials += 1
                    end = max(end, time.monotonic() + 3)
                    continue
            if time.monotonic() >= end:
                return None, None
            control.sleep(interval)

    def wait(self, key, timeout=15.0, interval=0.3):
        return self.wait_any([key], timeout, interval)[1]

    def wait_gone(self, key, timeout=15.0, interval=0.4):
        """Wait until the template is no longer on screen. True if it went."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not self.find(key):
                return True
            control.sleep(interval)
        return False

    # --- input -----------------------------------------------------------------------------
    def tap(self, x, y, jitter=3):
        control.checkpoint()
        j = jitter
        self.device.tap(x + (random.randint(-j, j) if j else 0), y + (random.randint(-j, j) if j else 0))

    def tap_burst(self, m, n, interval=0.05):
        """Tap a match n times in one quick burst (no checks in between)."""
        control.checkpoint()
        if n > 0:
            self.device.tap_burst(m.x, m.y, n, interval)

    def tap_point(self, name, **kw):
        x, y = self.layout.point(name)
        self.tap(x, y, **kw)

    def tap_match(self, m, **kw):
        self.tap(m.x, m.y, **kw)

    def tap_template(self, key, timeout=10.0, after=0.3):
        """Wait for a template and tap it. Returns True if it was tapped."""
        m = self.wait(key, timeout)
        if not m:
            return False
        self.tap_match(m)
        control.sleep(after)
        return True

    def swipe(self, a, b, ms=500):
        control.checkpoint()
        self.device.swipe(a[0], a[1], b[0], b[1], ms)

    def drag(self, a, b, ms=500):
        control.checkpoint()
        self.device.drag(a[0], a[1], b[0], b[1], ms)

    def sleep(self, seconds):
        control.sleep(seconds)

    # --- reading ---------------------------------------------------------------------------
    def read_number(self, region_name, retries=3, frame=None):
        """Read a number in a named region; retries on a new frame if unreadable."""
        region = self.layout.region(region_name)
        for attempt in range(retries):
            f = frame if (frame is not None and attempt == 0) else self.shot()
            value = vision.digits.read(f, region)
            if value is not None:
                return value
            control.sleep(0.3)
        return None

    # --- diagnostics -------------------------------------------------------------------------
    def save_error(self, label, frame=None):
        """Save the screen (or `frame`, a picture taken earlier) to logs/errors."""
        if not self.settings.get("save_error_screenshots", True):
            return None
        try:
            frame = self.device.capture() if frame is None else frame
        except Exception:
            return None
        name = f"{datetime.now():%Y%m%d-%H%M%S}-{label}.png"
        path = os.path.join(paths.ERROR_SHOTS, name)
        cv2.imencode(".png", frame)[1].tofile(path)
        log.info("Saved screenshot logs/errors/%s", name)
        return path
