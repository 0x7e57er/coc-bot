"""Stop / pause signals: F9 pauses and continues, F10 stops (global hotkeys).

Every input action and every wait calls `control.checkpoint()`, so a key press takes effect
within ~0.1 s. Pushing the mouse into a screen corner also stops the bot (pyautogui's fail-safe).
The run's watchdog uses the same door: `control.kick(reason)` makes the next checkpoint raise Stuck, which
is recovered from like any other error.
"""

import logging
import threading
import time

log = logging.getLogger("bot")


class BotStopped(Exception):
    """Raised inside the bot when Stop (F10) is pressed."""


class Stuck(Exception):
    """Raised inside the bot when the watchdog saw no progress for a long time: recovered from like an error."""


def is_user_abort(exc):
    """pyautogui's fail-safe (mouse pushed into a screen corner) counts as Stop."""
    return isinstance(exc, BotStopped) or type(exc).__name__ == "FailSafeException"


class Control:
    def __init__(self):
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._listener = None
        self._kick = None

    def reset(self):
        """Before a new run: not stopped, not paused."""
        self._stop.clear()
        self._pause.clear()
        self._kick = None

    def kick(self, reason):
        """The bot's next checkpoint raises Stuck(reason) (from the watchdog's thread)."""
        self._kick = reason

    def stop(self):
        self._stop.set()

    @property
    def paused(self):
        return self._pause.is_set()

    def toggle_pause(self):
        if self._pause.is_set():
            self._pause.clear()
            log.info("Continuing (F9)")
        else:
            self._pause.set()
            log.info("Paused - press F9 to continue, F10 to stop")

    @property
    def stopping(self):
        return self._stop.is_set()

    def start_hotkeys(self, pause="f9", stop="f10"):
        """Listen for the pause / stop keys anywhere in Windows."""
        if self._listener is not None:
            return
        from pynput import keyboard

        keys = {getattr(keyboard.Key, pause): self.toggle_pause, getattr(keyboard.Key, stop): self._stop_key}

        def on_press(key):
            fn = keys.get(key)
            if fn:
                fn()

        self._listener = keyboard.Listener(on_press=on_press, daemon=True)
        self._listener.start()

    def _stop_key(self):
        log.info("Stop pressed (F10)")
        self.stop()

    # --- called from the bot -----------------------------------------------------------------
    def checkpoint(self):
        if self._stop.is_set():
            raise BotStopped()
        while self._pause.is_set():
            if self._stop.is_set():
                raise BotStopped()
            time.sleep(0.1)
        if self._kick:
            reason, self._kick = self._kick, None
            raise Stuck(reason)

    def sleep(self, seconds):
        end = time.monotonic() + seconds
        while True:
            self.checkpoint()
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(0.1, left))


control = Control()
