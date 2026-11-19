"""The army screen and the first saved army selected from the Saved Recipes dropdown."""

import logging
import time

from . import vision
from .context import BotError
from .states import go_home
from .space import space

log = logging.getLogger("bot")


def open_army(bot):
    """The army screen: Battle -> Edit Army."""
    if not go_home(bot):
        raise BotError("Not on the home village")
    bot.tap_point("home.attack")
    if not bot.wait_any(["attack_menu/find_match", "attack_menu/edit_army"], 6, interval=0.2)[0]:
        bot.save_error("no-battle-menu")
        raise BotError("Battle menu did not open")
    bot.tap_point("attack_menu.edit_army")
    if not bot.wait("army/my_army_title", 8, interval=0.25):
        raise BotError("Army screen did not open")
    bot.sleep(0.35)


def close_army(bot):
    m = bot.find("army/close")
    bot.tap_match(m, jitter=2) if m else bot.tap_point("army.close")
    bot.sleep(0.4)
    if bot.exists("attack_menu/find_match"):         # back in the Battle menu: close it too
        bot.tap_point("attack_menu.close")
        bot.sleep(0.4)


def use_first_recipe(bot):
    """Select the first saved army from the dropdown beside Saved Recipes on the My Army tab.

    The dropdown lists saved recipe names directly (newer game UI). We read the first
    visible option and tap the row centre; no recipe name is hard-coded.
    Returns the selected name, or None when the menu / option could not be verified.
    """
    open_army(bot)
    try:
        frame = bot.shot()
        scales = (0.80, 0.85, 0.90, 0.928, 0.95, 1.0, 1.05, 1.10, 1.15)
        arrow, scale = vision.find_scaled(
            frame, "army/recipes_arrow", scales=scales, threshold=0.78,
            region=space.region(1010, 65, 280, 205),
        )
        if not arrow:
            log.warning("Army: Saved Recipes dropdown arrow not found")
            bot.save_error("army-recipe-dropdown-arrow", frame)
            return None

        bot.tap_match(arrow, jitter=2)
        bot.sleep(0.4)
        frame = bot.shot()
        menu_region = space.region(840, 180, 630, 510)
        lines = vision.text_reader.read(frame, menu_region)

        # Menu options are rows below the arrow. Ignore nearby panel headings and controls.
        options = []
        for text, confidence, box in lines:
            x, y, w, h = box
            cx, cy = x + w / 2, y + h / 2
            value = (text or "").strip()
            if not value or confidence < 0.30:
                continue
            if not (arrow.x - space.s(300) <= cx <= arrow.x + space.s(300)):
                continue
            if not (arrow.y + space.s(45) <= cy <= arrow.y + space.s(430)):
                continue
            if value.lower().replace(" ", "") in ("savedrecipes", "cookbook", "myarmy"):
                continue
            options.append((y, value, confidence, box))

        if not options:
            log.warning("Army: Saved Recipes dropdown opened but no recipe names were readable")
            bot.save_error("army-recipe-dropdown-unreadable", frame)
            return None

        _, name, confidence, box = min(options, key=lambda item: item[0])
        _, y, _, h = box
        target = (arrow.x, int(y + h / 2))
        log.info("Army: selecting first Saved Recipes dropdown option '%s' (OCR %.2f)", name, confidence)
        bot.tap(*target, jitter=1)

        # The game may ask to confirm replacing Clan Castle troops. Handle that only
        # when its explicit Okay button is visible.
        deadline = time.monotonic() + 2.5
        selected = False
        after = bot.shot()
        while time.monotonic() < deadline:
            after = bot.shot()
            okay = vision.find(after, "battle/confirm_okay")
            if okay:
                bot.tap_match(okay, jitter=2)
                bot.sleep(0.65)
                log.info("Army: confirmed loading the saved recipe with Clan Castle troops")
                selected = True
                break

            after_lines = vision.text_reader.read(after, menu_region)
            still_open = any(
                (t or "").strip().casefold() == name.casefold()
                and y0 >= arrow.y + space.s(45)
                for t, conf, (x0, y0, w0, h0) in after_lines if conf >= 0.30
            )
            if not still_open:
                selected = True
                break
            bot.sleep(0.2)

        if not selected:
            log.warning("Army: dropdown option '%s' remained visible after selection; not confirmed", name)
            bot.save_error("army-recipe-selection-unconfirmed", after)
            return None

        log.info("Army: selected saved recipe '%s' from the dropdown", name)
        return name
    finally:
        close_army(bot)
        go_home(bot)

