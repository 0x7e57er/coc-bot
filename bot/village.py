"""Builder Base -> home village. An account can open on its Builder Base (the night village) when it
was left there; the bot sails back home with the boat before it loots."""

import logging
import time

from . import vision
from .context import BotError
from .control import control
from .space import space
from .states import detect

log = logging.getLogger("bot")

BB_MARK = "bb/trophy_hammer"     # the hammer by the trophy count: only shown in the Builder Base


def where(bot):
    """'main', 'builder' or None (unknown)."""
    f = bot.shot()
    if vision.find(f, BB_MARK):
        return "builder"
    if detect(f) == "home":
        return "main"
    return None


def go_home_bb(bot, timeout=60.0):
    """Get back to the Builder Base village from any of its screens."""
    from .states import cancel_placement
    cancel_placement(bot)                            # a building left waiting to be placed
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        f = bot.shot()
        if vision.find(f, BB_MARK):
            return True
        for key in ("bb/star_bonus_okay", "bb/return_home", "bb/menu_close", "upgrade/close", "lab/close",
                    "shop/close"):
            if vision.templates.has(key):
                m = vision.find(f, key)
                if m:
                    bot.tap_match(m)
                    break
        else:
            st = detect(f)
            if st == "home":
                return False                         # we are in the main village
            if st == "exit_dialog":
                bot.tap_point("dialog.cancel")       # never quit the game
                control.sleep(0.6)
                continue
            bot.tap_point("bb.safe", jitter=5)
        control.sleep(0.6)
    return False


def _find_boat(bot):
    """Find the boat of the current village. Its little ship icon (in a bubble above the boat)
    is the same in every scenery and both villages, only its size changes with the zoom, so
    it is searched at several sizes. If it is not on screen, pan in a fixed pattern."""
    pans = [None, ((1300, 300), (600, 800)), ((1300, 300), (600, 800)), ((600, 800), (1300, 300)),
            ((600, 800), (1300, 300)), ((600, 800), (1300, 300)), ((700, 300), (1300, 800)),
            ((1300, 800), (700, 300)), ((1300, 800), (700, 300))]
    for pan in pans:
        control.checkpoint()
        if detect(bot.shot()) not in ("home", "bb_home"):
            return None                              # not on a village (a popup opened): never swipe over it
        if pan:
            bot.swipe(space.center(*pan[0]), space.center(*pan[1]), 600)
            control.sleep(0.6)
        m, sc = vision.find_scaled(bot.shot(), "boat/icon")
        if m:
            # the boat is under its icon; near the bottom the button bar covers the boat: tap just under
            # the icon then (the bubble itself is the boat's too)
            y = int(m.y + 80 * sc)
            if y > space.point(0, 930)[1]:
                y = int(m.y + 45 * sc)
            return type(m)(m.x, y, m.score, m.box)
    return None


def travel_home(bot):
    """Sail from the Builder Base back to the home village."""
    here = where(bot)
    if here == "main":
        return True
    if here is None:
        go_home_bb(bot, 20)
        here = where(bot)
        if here == "main":
            return True
    boat = None
    for _ in range(2):
        bot.tap_point("bb.safe", jitter=5)          # deselect anything first
        bot.device.zoom_out()
        control.sleep(0.5)
        boat = _find_boat(bot)
        if boat is not None:
            break
        go_home_bb(bot, 20)                          # clear the screen and look again
        control.sleep(1.0)
    if boat is None:
        raise BotError("Could not find the boat back to the home village")
    bot.tap_match(boat, jitter=3)
    start = time.monotonic()
    retapped = False
    while time.monotonic() - start < 60:              # loading the other village can take a while
        control.sleep(1.0)
        now = where(bot)
        if now == "main":
            log.info("Now in the home village")
            return True
        if now == "builder" and not retapped and time.monotonic() - start > 8:
            boat = _find_boat(bot)                    # the tap did not register: tap the boat again
            if boat:
                bot.tap_match(boat, jitter=3)
            retapped = True
        f = bot.shot()
        m = vision.templates.has("bb/star_bonus_okay") and vision.find(f, "bb/star_bonus_okay")
        if m:
            bot.tap_match(m)
    raise BotError("The boat did not sail back to the home village")
