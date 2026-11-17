"""The army screen (Battle -> Edit Army) and the army for looting: the Saved Recipes tab -> Use on the first
recipe."""

import logging
import time

from . import vision
from .context import BotError
from .states import go_home

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
    """The army for looting: army screen -> the Saved Recipes tab -> Use on the first recipe (the top card). The game
    asks to confirm it only when the Clan Castle has troops: then Okay. Returns the recipe's name ("" when it could
    not be read), or None when no recipe could be used (the army is left as it is)."""
    open_army(bot)
    try:
        uses = []
        for _ in range(2):
            tab = bot.wait("army/recipes_tab", 3, interval=0.25)
            if not tab:
                break
            bot.tap_match(tab, jitter=3)
            bot.sleep(1.0)
            frame = bot.shot()
            uses = sorted(vision.find_all(frame, "army/recipe_use"), key=lambda m: m.y)
            if uses:
                break
        if not uses:
            bot.save_error("army-no-recipes")
            log.warning("Army: no recipe to use on the Saved Recipes tab (none saved?)")
            return None
        first = uses[0]
        k = first.box[2] / vision.templates.image("army/recipe_use").shape[1]
        name, _ = vision.text_reader.read_line(frame, (int(first.x - 1340 * k), int(first.y - 72 * k), int(420 * k),
                                                        int(40 * k)))
        bot.tap_match(first, jitter=3)
        end = time.monotonic() + 2.5                # Okay only when the game asks (troops in the Clan Castle)
        while time.monotonic() < end:
            bot.sleep(0.25)
            m = vision.find(bot.shot(), "battle/confirm_okay")
            if m:
                bot.tap_match(m)
                log.info("Army: the Clan Castle has troops - confirmed the recipe")
                bot.sleep(0.7)
                break
        return name.strip()
    finally:
        close_army(bot)
        go_home(bot)
