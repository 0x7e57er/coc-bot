"""Looting: read storages, search for a base with enough loot, attack, come home.

An account is full when its watched resource reaches the "full storage" written in
config/settings.json for the account's Town Hall (accounts.json), or the account's own "full_at".
"""

import logging
import time

from . import army, attack, config, vision
from .context import BotError
from .control import control
from .states import go_home

log = logging.getLogger("bot")


def watched(settings):
    w = settings["loot"]["watch"]
    return [r for r in config.RESOURCES if w.get(r)] or ["elixir"]


def home_resources(bot):
    """Current gold/elixir/dark on the home screen (None where unreadable)."""
    frame = bot.shot()
    return {r: bot.read_number(f"home.{r}", frame=frame) for r in config.RESOURCES}


def fullness(bot, account, res):
    """{resource: (value, full_at, is_full)} for the watched resources."""
    out = {}
    for r in watched(bot.settings):
        cap = config.full_at(bot.settings, account, r)
        v = res.get(r)
        out[r] = (v, cap, bool(cap and v is not None and v >= cap))
    return out


def is_full(bot, account, res):
    f = fullness(bot, account, res)
    flags = [full for _, _, full in f.values()]
    rule = bot.settings["loot"]["full_rule"]
    return (all(flags) if rule == "all" else any(flags)), f


def loot_is_good(settings, loot, account):
    """Is the scouted base worth attacking? (the minimum is by the attacking account's Town Hall)"""
    mins = config.min_loot(settings, account)
    checks = [(loot.get(r) or 0) >= mins.get(r, 0) for r in watched(settings) if mins.get(r, 0) > 0]
    if not checks:
        return True
    return all(checks) if settings["loot"]["min_loot_rule"] == "all" else any(checks)


SEARCH_GOLD = 5_000       # less gold than this: no search (Find a Match / Next cost gold; never gems)


class NoGold(BotError):
    """Too little gold to search for a base."""


def collect_gold(bot):
    """Tap the full gold collectors' bubbles (and the elixir / dark ones) on the village (zoomed out:
    the bubbles' pictures are taken that way)."""
    bot.device.zoom_out()
    control.sleep(0.5)
    f = bot.shot()
    full = (0, 0, f.shape[1], f.shape[0])
    tapped = 0
    for key in ("village/bubble_gold", "village/bubble_elixir", "village/bubble_dark"):
        if vision.templates.has(key):
            for m in vision.find_all(f, key, region=full)[:2]:
                bot.tap_match(m, jitter=2)
                bot.sleep(0.5)
                tapped += 1
    return tapped


def start_search(bot):
    bot.action = "Finding a match"
    if not go_home(bot):
        raise BotError("Not on the home village")
    gold = bot.read_number("home.gold")
    if gold is not None and gold < SEARCH_GOLD:
        if collect_gold(bot):
            bot.sleep(1.0)
            gold = bot.read_number("home.gold")
        if gold is not None and gold < SEARCH_GOLD:
            raise NoGold(f"only {gold:,} gold: not enough to search a base")
    if bot.settings["loot"].get("zoom_out", True):
        bot.device.zoom_out()                       # 2 presses: one is not always enough (the battle keeps it)
        control.sleep(0.3)
    bot.tap_point("home.attack")
    if not bot.tap_template("attack_menu/find_match", timeout=8, after=0.4):
        raise BotError("Attack menu did not open")
    if not bot.tap_template("army/attack_button", timeout=8, after=0.5):
        bot.save_error("no-army-attack")
        raise BotError("Army 'Attack!' button not found (army not ready?)")


def stable_loot(bot, max_wait=2.0):
    """The scouted loot, read until two reads 0.25 s apart agree: the numbers count up for a
    moment when a base appears, so a single early read could be too low."""
    end = time.monotonic() + max_wait
    prev = None
    while True:
        frame = bot.shot()
        loot = {r: vision.digits.read(frame, bot.layout.region(f"scout.{r}")) for r in config.RESOURCES}
        if prev is not None and loot == prev and loot.get("gold") is not None:
            return loot
        if time.monotonic() > end:
            # still changing or unreadable: one last careful read
            return {r: bot.read_number(f"scout.{r}") for r in config.RESOURCES}
        prev = loot
        control.sleep(0.25)


def search(bot, account):
    """Press Next until a base meets the loot minimum. Returns the loot dict or None."""
    max_searches = bot.settings["loot"]["max_searches"]
    for n in range(1, max_searches + 1):
        key, _ = bot.wait_any(["scout/next", "scout/end_battle"], timeout=30)
        if key == "scout/end_battle" and not bot.wait("scout/next", timeout=4):
            # a base is shown but no Next: the gold for the next search is not there -> attack this one
            loot = stable_loot(bot)
            log.info("Search %d: %s -> attack (no gold left for Next)", n, _fmt(loot))
            return loot
        if key is None:
            bot.save_error("no-scout")
            raise BotError("Scouting screen did not appear")
        bot.action = f"Searching #{n}"
        loot = stable_loot(bot)
        bot.stats["searches"] += 1
        bot.last_loot = loot
        if loot_is_good(bot.settings, loot, account):
            log.info("Search %d: %s -> attack", n, _fmt(loot))
            return loot
        log.debug("Search %d: %s -> next", n, _fmt(loot))
        bot.tap_point("scout.next")
        control.sleep(0.5)
    log.info("No base found in %d searches", max_searches)
    return None


def attack_once(bot, account):
    """One full attack from the home village back to the home village.
    Returns the scouted loot, or None if no good base was found."""
    start_search(bot)
    loot = search(bot, account)
    if loot is None:
        go_home(bot)
        return None
    s = bot.settings["loot"]
    plan = attack.get_plan(s["attack_plan"])
    started = time.monotonic()
    bot.action = "Deploying"
    attack.deploy(bot, plan)
    started = getattr(bot, "deploy_started", None) or started    # from the first unit (deploying counts)
    bot.action = "Battle"
    attack.finish_battle(bot, s["battle_seconds"], started, stall=s.get("end_when_loot_stops", 0),
                         watch=config.RESOURCES)  # any loot still going down: the troops are still looting
    bot.stats["attacks"] += 1
    bot.action = "Going home"
    if not go_home(bot, timeout=90):          # results -> reward chest -> home
        raise BotError("Did not get home after the battle")
    return loot


def loot_until_full(bot, account):
    """Attack until the account's watched storages are full.
    Returns "full", "limit" (max attacks reached), "stuck" (storages stopped growing), "no_army" (no army
    with the required units) or "no_gold" (too little gold to search, even after collecting it)."""
    s = bot.settings["loot"]
    limit = s["max_attacks_per_account"]
    attacks = 0
    stuck = 0
    before = None
    while True:
        control.checkpoint()
        if not go_home(bot):
            raise BotError("Not on the home village")
        bot.action = "Reading storages"
        res = home_resources(bot)
        full, detail = is_full(bot, account, res)
        bot.progress[account["name"]] = {"status": "looting", "res": res}
        log.info("%s (TH %s): %s", account["name"], account.get("th") or "?", _fmt_full(detail))
        if full:
            return "full"
        if limit and attacks >= limit:
            return "limit"
        if before is not None:
            grew = any((res.get(r) or 0) > (before.get(r) or 0) for r in watched(bot.settings))
            stuck = 0 if grew else stuck + 1
            if stuck >= s.get("stuck_attacks", 2):
                log.info("%s: storages stopped growing -> treating as full", account["name"])
                return "stuck"
            for r in config.RESOURCES:
                if res.get(r) is not None and before.get(r) is not None and res[r] > before[r]:
                    bot.stats["loot"][r] += res[r] - before[r]
        before = res
        if not ensure_army(bot, account):        # only now: the account really is going to attack
            return "no_army"
        try:
            if attack_once(bot, account) is not None:
                attacks += 1
        except NoGold as e:
            log.warning("%s: %s - not looted now", account["name"], e)
            return "no_gold"


def ensure_army(bot, account):
    """Before the first attack of a visit: army screen -> Saved Recipes -> the first recipe (confirmed only when the
    game asks: troops in the Clan Castle). When that fails the account attacks with the army it has. True."""
    if account.get("_army_set"):
        return True
    bot.action = "Setting the army: Saved Recipes > Use on the top recipe"
    name = army.use_first_recipe(bot)
    account["_army_set"] = True
    if name is None:
        log.info("%s: no saved recipe to apply; keeping the army already loaded in-game", account["name"])
    elif name:
        log.info("%s: loaded saved recipe '%s'", account["name"], name)
    else:
        log.info("%s: loaded the first saved recipe (its name could not be read)", account["name"])
    return True


def _fmt(d):
    return ", ".join(f"{k} {v:,}" if v is not None else f"{k} ?" for k, v in d.items())


def _fmt_full(detail):
    parts = []
    for r, (v, cap, full) in detail.items():
        vs = f"{v:,}" if v is not None else "?"
        cs = f"{cap:,}" if cap else "no full storage set for this Town Hall"
        parts.append(f"{r} {vs} / {cs}{' FULL' if full else ''}")
    return "; ".join(parts)
