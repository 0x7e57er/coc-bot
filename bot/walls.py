"""Loot + walls: the loot is put into walls once the account has looted, with the game's "Upgrade More" (many walls of
one level in one go).

The Build panel lists the walls by level: "Wall x 25" and the cost of one wall (1,000 gold for level 1 ... 10,000,000
for level 19). A wall row tapped selects one of those walls in the village, with buttons under it: Info, Select Row,
**Upgrade More** and Upgrade. Upgrade More turns it into "Wall (Level 1) x 1" with Remove Wall (-1), Add Wall (+10),
Add Wall (+1) and the Upgrade buttons showing the total cost; "Add Wall" is red when no more can be added. Upgrade asks
"Upgrade Walls - Do you really want to upgrade the selected Walls for 11000 Gold?" - Okay.

Gold pays for every level. The higher levels show two Upgrade buttons, gold and elixir, at the same price. So the bot
uses both: on each level the resource that pays for the most walls goes first, then the other one pays for the walls
left. A level that takes only gold is skipped when there is no gold to spend, and a visit whose gold / elixir pays for
no wall the account has does not open the list at all (the account's levels and what pays for them are remembered).

Cheapest walls first: the wall row is tapped, Upgrade More, Add Wall until the walls the budget pays for are selected,
Upgrade with that resource, and Okay only when the box asks exactly that amount of that resource. Nothing else is ever
tapped there (never gems).
"""

import logging
import re
import time

from . import config, loot, upgrade, vision
from .context import BotError
from .control import control
from .states import go_home

log = logging.getLogger("bot")

PAY = ("gold", "elixir")    # walls are paid with gold (all levels) or elixir (the higher levels)
MAX_BATCHES = 20            # Upgrade More batches in one visit at most
TITLE_ABOVE = 290           # the "Wall (Level 1) x 11" title is this far above the Upgrade buttons


def _count(text):
    """ "Wall (Level 19)x 11" / "Wallx150" -> 11 / 150 (the number after the last x)."""
    m = re.findall(r"[x×]\s*(\d+)", text.lower())
    return int(m[-1]) if m else None


def wall_rows(bot, x):
    """Every wall row of the Build panel: [{"name", "cost" (one wall), "count", "page"}] - the list is read to its
    end (it is opened again at its top afterwards)."""
    rows, seen = [], set()
    for page in range(upgrade.SCROLLS + 1):
        for r in upgrade.read_rows(bot.shot(), x):
            if upgrade.key(r["name"]).startswith("wall") and (r["name"], r["cost"]) not in seen:
                seen.add((r["name"], r["cost"]))
                rows.append(dict(r, count=_count(r["name"]) or 1, page=page))
        if page == upgrade.SCROLLS or not upgrade._scroll(bot, x):
            break
    return rows


def _buttons(frame):
    """The Upgrade More view: ({"+10": match, "+1": match} of the Add Wall buttons that can be pressed (white),
    [(upgrade button, resource, total cost shown)])."""
    adds = {}
    for m in vision.find_all(frame, "walls/add_wall"):
        label, _ = vision.text_reader.read_line(frame, (m.x - 5, m.y - 68, 75, 42))
        adds["+10" if "10" in label else "+1"] = m
    ups = []
    for m in vision.find_all(frame, "walls/upgrade"):
        text, _ = vision.text_reader.read_line(frame, (m.x - 70, m.y - 80, 120, 30))
        digits = re.sub(r"\D", "", text)
        ups.append((m, upgrade._resource(frame, m.x + 57, m.y - 65), int(digits) if digits else None))
    return adds, ups


def _title_count(frame, ups):
    """How many walls the Upgrade More view's title says are selected ("Wall (Level 1)x 11"), or None."""
    if not ups:
        return None
    cx = sum(m.x for m, _, _ in ups) // len(ups)
    y = ups[0][0].y - TITLE_ABOVE
    lines = vision.text_reader.read(frame, (cx - 300, y - 28, 600, 56))
    return _count(" ".join(t for t, _, _ in lines))


def _total(ups, res):
    """The total cost on the Upgrade button of that resource (None when there is none or it is unread)."""
    return next((t for _, r, t in ups if r == res), None)


def _have(frame, ups, res, unit):
    """Walls selected: the Upgrade button's total / the cost of one wall (the title when the total is unread)."""
    t = _total(ups, res)
    if t and t % unit == 0:
        return t // unit
    return _title_count(frame, ups)


def _choose(ups, budget, unit):
    """(resource, walls it pays for) for this batch: of the Upgrade buttons shown, the one whose budget pays for the
    most walls; (None, 0) when none pays for one."""
    n, res = max(((budget.get(r, 0) // unit, r) for _, r, _ in ups if r in budget), default=(0, None))
    return (res, n) if n >= 1 else (None, 0)


def _levels(bot, name):
    """{cost of one wall: [resources that pay for it] or None (not opened yet)} of the account's wall levels, as seen
    at its last visits."""
    return {int(c): rs for c, rs in bot.state.get("walls_levels", {}).get(name, {}).items()}


def _remember(bot, name, costs=None, cost=None, pays=None):
    """The account's wall levels: `costs` - the levels the Build list shows now (the others are gone); `cost` +
    `pays` - the resources one level's Upgrade buttons take."""
    old = _levels(bot, name)
    new = {c: old.get(c) for c in costs} if costs is not None else dict(old)
    if cost is not None and pays:
        new[cost] = sorted(pays)
    if new != old:
        bot.state.setdefault("walls_levels", {})[name] = {str(c): rs for c, rs in sorted(new.items())}
        config.save_state(bot.state)


def _payable(levels, budget, cost):
    """The resources above what is kept that pay for one wall of this level."""
    return [r for r in (levels.get(cost) or PAY) if budget.get(r, 0) >= cost]


def _waits(bot, name, cost):
    """Seconds these walls wait for a builder: since the November 2026 update the higher walls need a free builder
    (the game says "all your Builders are busy" otherwise). The cheapest level that asked for one is remembered,
    and with it until when every builder is busy; 0 when they can be tried."""
    need = bot.state.get("walls_builder", {}).get(name)
    left = bot.state.get("builders_busy", {}).get(name, 0) - time.time()
    return left if need is not None and cost >= need and left > 0 else 0


def _builders_busy(bot, name, cost, x):
    """The game said every builder is busy for these walls: remember it (until the first upgrade in progress is
    done, read from the Build panel)."""
    need = bot.state.setdefault("walls_builder", {})
    need[name] = min(need.get(name, cost), cost)
    wait = (upgrade.soonest_done(bot.shot(), x) if x else None) or 1800
    bot.state.setdefault("builders_busy", {})[name] = time.time() + wait
    config.save_state(bot.state)
    log.info("%s: walls of %s and up need a free builder, and every builder is busy for another %s - they wait",
             name, f"{need[name]:,}", upgrade._span(wait))


def _worth(bot, name, budget):
    """Does the gold / elixir above what is kept pay for one wall the account had at its last visit (one whose
    builder is free)? True when its walls are not known yet."""
    levels = _levels(bot, name)
    if not levels:
        return max(budget.values(), default=0) > 0
    return any(_payable(levels, budget, c) and not _waits(bot, name, c) for c in levels)


def _confirm(bot, amount, res):
    """The "Upgrade Walls" box: Okay only when it asks exactly `amount` of `res`. True when Okay was tapped."""
    title = bot.wait("walls/confirm_title", 4, interval=0.25)
    if not title:
        log.info("Walls: the Upgrade Walls box did not show")
        return False
    f = bot.shot()
    lines = vision.text_reader.read(f, (title.x - 340, title.y + 85, 680, 95))
    asked, word = _asked(" ".join(t for t, _, _ in lines))
    if asked != amount or word != res:
        log.warning("Walls: the box asks %s %s, not %s %s - Cancel", f"{asked:,}" if asked else "?", word or "?",
                    f"{amount:,}", res)
        bot.save_error("walls-confirm", f)
        bot.tap_point("dialog.cancel", jitter=2)
        bot.sleep(0.6)
        return False
    m = bot.wait("battle/confirm_okay", 3, interval=0.25)   # (a BlueStacks toast can cover it for a moment)
    if not m:
        log.info("Walls: no Okay in the Upgrade Walls box - Cancel")
        bot.save_error("walls-no-okay")
        bot.tap_point("dialog.cancel", jitter=2)    # never left open: going home would press its Okay
        bot.sleep(0.6)
        return False
    bot.tap_match(m, jitter=2)
    bot.sleep(0.5)
    return True


def _asked(text):
    """ "...the selected Walls for 11o00 Gold?" -> (11000, "gold"); (None, None) when unread."""
    t = re.sub(r"(?<=\d)[oO]|[oO](?=\d)", "0", text).lower().replace(" ", "")
    m = re.search(r"(\d[\d,.]*)(gold|elixir)", t)
    return (int(re.sub(r"\D", "", m.group(1))), m.group(2)) if m else (None, None)


def _upgrade_level(bot, row, budget, name):
    """The wall row is tapped: Upgrade More, choose the resource, add the walls its budget pays for, Upgrade, Okay.
    Returns (walls, resource, amount), "busy" (these walls need a builder and none is free) or None."""
    more = bot.wait("walls/upgrade_more", 4, interval=0.25)
    if not more:
        log.info("Walls: no Upgrade More under the selected wall")
        return None
    bot.tap_match(more, jitter=3)
    bot.sleep(0.9)
    frame = bot.shot()
    adds, ups = _buttons(frame)
    if not ups:
        log.info("Walls: the Upgrade More view did not open")
        return None
    unit = row["cost"]
    takes = [r for _, r, _ in ups if r in PAY]
    _remember(bot, name, cost=unit, pays=takes)
    res, can = _choose(ups, budget, unit)
    if res is None:
        log.info("Walls: %s (%s each, paid with %s) - not enough of that above what is kept (%s)", row["name"],
                 f"{unit:,}", " or ".join(takes) or "?", loot._fmt(budget))
        return None
    want = min(row["count"], can)
    have = _have(frame, ups, res, unit) or 1
    log.debug("Walls: %s pays for %d of the %d %s wall(s); %d selected", res, can, row["count"], f"{unit:,}", have)
    for _ in range(40):                              # Add Wall until `want` are selected
        if have >= want:
            break
        # +10 only while 10 more fit (it never goes past the budget)
        key = "+10" if want - have >= 10 and "+10" in adds else "+1" if "+1" in adds else None
        if key is None:
            break                                    # nothing more can be added (red)
        bot.tap_match(adds[key], jitter=2)
        bot.sleep(0.35)
        frame = bot.shot()
        adds, ups = _buttons(frame)
        have = _have(frame, ups, res, unit) or have
    btn = next((m for m, r, _ in ups if r == res), None)
    total = _total(ups, res)
    seen = _title_count(frame, ups)
    if btn is None or not total or total % unit or total > budget.get(res, 0) or (seen and seen != total // unit):
        log.warning("Walls: %s - the %s Upgrade shows %s for %s wall(s) of %s each - not upgraded", row["name"], res,
                    f"{total:,}" if total else "?", seen or "?", f"{unit:,}")
        bot.save_error("walls-cost", frame)
        return None
    had = loot.home_resources(bot).get(res)          # the storage bar stays on screen in this view
    bot.tap_match(btn, jitter=3)
    if not _confirm(bot, total, res):
        return None
    done = _result(bot, res, had, total)
    if done == "busy":
        return "busy"
    if done != "paid":
        log.warning("Walls: Okay was tapped, but the %s storage did not go down by %s (%s before) - not counted",
                    res, f"{total:,}", f"{had:,}" if had is not None else "?")
        bot.save_error("walls-not-paid")
        return None
    return total // unit, res, total


def _result(bot, res, had, amount, seconds=4):
    """After Okay: "paid" (the storage of `res` went down by `amount`, or it cannot be read - the box asked exactly
    that amount), "busy" (the game says every builder is busy: these walls need a builder; the box is closed with
    its X, never its gem button) or "unpaid"."""
    end = time.monotonic() + seconds
    now = None
    while time.monotonic() < end:
        f = bot.shot()
        busy = vision.find(f, "upgrade/builders_busy")
        if busy:
            upgrade._close_busy(bot, busy)
            return "busy"
        now = loot.home_resources(bot).get(res)
        if had is not None and now is not None and had - now >= amount * 0.99:
            log.debug("Walls: %s %s -> %s", res, f"{had:,}", f"{now:,}")
            return "paid"
        bot.sleep(0.4)
    return "paid" if had is None or now is None else "unpaid"


def _goto(bot, x, row):
    """The panel opened again at its top and dragged to the row's page: the row as it reads there (a wall row of the
    same cost; its count may have changed), or None."""
    upgrade.close_panel(bot)
    x = upgrade.open_panel(bot)
    for page in range(upgrade.SCROLLS + 1):          # from the page above its own to the end: upgrades move rows
        if page >= row["page"] - 1:
            for r in upgrade.read_rows(bot.shot(), x):
                if upgrade.key(r["name"]).startswith("wall") and r["cost"] == row["cost"]:
                    return dict(row, y=r["y"], count=_count(r["name"]) or row["count"], page=page), x
        if page == upgrade.SCROLLS or not upgrade._scroll(bot, x):
            break
    return None, x


def spend(bot, account):
    """Put the gold / elixir above what is kept into walls, cheapest first, with both resources. Returns the number of
    walls upgraded. The Build list is read once per visit (about 50 s); a visit whose gold / elixir pays for no wall
    the account had last time does not open it at all."""
    s = bot.settings.get("walls", {})
    name = account["name"]
    if not go_home(bot):
        raise BotError("Not on the home village")
    bot.action = "Walls: reading storages"
    before = loot.home_resources(bot)
    budget = {r: max(0, (before.get(r) or 0) - int(s.get("keep", {}).get(r, 0) or 0))
              for r in PAY if s.get("spend", {}).get(r, True) and before.get(r) is not None}
    if not _worth(bot, name, budget):
        levels = _levels(bot, name)
        costs = ", ".join(f"{c:,} ({'/'.join(rs) if rs else '?'}{', waits for a builder' if _waits(bot, name, c) else ''})"
                          for c, rs in levels.items())
        log.info("%s: nothing above what is kept pays for a wall that can be upgraded now (can spend %s; walls cost %s)",
                 name, loot._fmt(budget), costs)
        return 0
    x = upgrade.open_panel(bot)
    done = batches = 0
    try:
        bot.action = "Walls: reading the Build list"
        rows = sorted(wall_rows(bot, x), key=lambda r: r["cost"])
        _remember(bot, name, costs=[r["cost"] for r in rows])
        levels = _levels(bot, name)
        log.info("%s: walls %s; can spend %s", name,
                 ", ".join(f"{r['count']} at {r['cost']:,} ({'/'.join(levels.get(r['cost']) or ['?'])})"
                           for r in rows) or "none listed", loot._fmt(budget))
        for row in rows:
            if row["cost"] > max(budget.values(), default=0):
                break                                        # (sorted: the others cost more)
            wait = _waits(bot, name, row["cost"])
            if wait:
                log.info("%s: walls of %s and up wait for a free builder (%s)", name, f"{row['cost']:,}",
                         upgrade._span(wait))
                break
            left = row["count"]
            for _ in PAY:                                    # one batch per resource at most
                control.checkpoint()
                pays = _payable(_levels(bot, name), budget, row["cost"])
                if left < 1 or not pays or batches >= MAX_BATCHES:
                    if not pays and left == row["count"]:
                        log.debug("Walls: %d at %s - takes %s, can spend %s", left, f"{row['cost']:,}",
                                  "/".join(_levels(bot, name).get(row["cost"]) or PAY), loot._fmt(budget))
                    break
                batches += 1
                bot.action = f"Walls: {left} at {row['cost']:,} ({' or '.join(pays)})"
                found, x = _goto(bot, x, row)
                if found is None:
                    log.info("Walls: the %s wall row was not found again", f"{row['cost']:,}")
                    break
                bot.tap(x.x - upgrade.PANEL_LEFT + 160, found["y"], jitter=4)
                bot.sleep(1.2)
                got = _upgrade_level(bot, found, budget, name)
                x = upgrade._panel(bot.shot()) or upgrade.open_panel(bot)
                if got == "busy":
                    _builders_busy(bot, name, found["cost"], x)
                    break
                if not got:
                    break
                walls, res, amount = got
                budget[res] -= amount
                left = found["count"] - walls
                row = dict(found, count=left)
                done += walls
                bot.stats["walls"] = bot.stats.get("walls", 0) + walls
                log.info("%s: %d wall(s) upgraded (%s each) for %s %s; left to spend %s", name, walls,
                         f"{found['cost']:,}", f"{amount:,}", res, loot._fmt(budget))
    finally:
        upgrade.close_panel(bot)
        go_home(bot)
    if done:
        after = loot.home_resources(bot)
        log.info("%s: %d wall(s) upgraded; storages %s -> %s", name, done, loot._fmt(before), loot._fmt(after))
    p = bot.progress.setdefault(name, {})
    p["walls"] = p.get("walls", 0) + done
    return done
