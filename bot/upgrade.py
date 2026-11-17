"""Loot + upgrade: the loot is spent on upgrades by the free builders, straight from the game's Build panel.

The Build button (bottom right of the village) opens "Buildings & Heroes" on the right:
  - the upgrades in progress (a green bar and the time left, no cost);
  - "Suggested upgrades", then "Other upgrades": a name ("Inferno Tower x 3"), the time and the cost, with a gold /
    elixir / dark elixir icon after it;
  - at the bottom the builders: "1/7" = 1 of 7 free.
A row tapped opens its upgrade window: a green Confirm with the cost (and a grey "Hammer of Building" - a magic item,
never used) and an X.

What may be upgraded is your list (settings "upgrade.list": every building, ticked or not, in your order):
  - "order": "game" - the game's own order (suggested first): the first row the account can pay, unticked ones
    skipped (a name not in the list is allowed);
  - "order": "mine" - only ticked ones, the highest in your list first: the whole Build list is read (scrolled),
    then the best one the account can pay is tapped.
While a builder is free that row is tapped, and the green Confirm tapped only when it shows exactly that cost.
Nothing is ever paid with gems: no free builder or not enough resources -> nothing is tapped, and any other window
that comes up is closed.
"""

import difflib
import logging
import re
import time

import cv2

from . import config, loot, vision
from .context import BotError
from .control import control
from .states import go_home

log = logging.getLogger("bot")

# Places in the panel, from its X (build/close) as BlueStacks draws it (game-space px)
PANEL_LEFT = 405            # the panel's left edge is this far left of the X
ROWS_TOP, ROWS_BOTTOM = 30, 775     # the list, below the X
TABS = 781                  # the tabs at the bottom start this far below the X; the builders' tab is the first
NAME_X = 75                 # names start this far right of the panel's left edge
COST_X = 250                # costs are right of this
SCROLLS = 8                 # the list is scrolled down at most this often (it is read to its end)

# Every home-village building and hero the Build panel can list, in a sensible order. Your list (settings
# "upgrade.list") is this one, ticked and ordered your way; names you add are matched the same way.
TOWN_HALL = ["Town Hall"]
DEFENSES = ["Cannon", "Archer Tower", "Mortar", "Air Defense", "Wizard Tower", "Air Sweeper", "Hidden Tesla",
            "Bomb Tower", "X-Bow", "Inferno Tower", "Eagle Artillery", "Scattershot", "Spell Tower", "Monolith",
            "Builder's Hut", "Multi-Archer Tower", "Ricochet Cannon", "Multi-Gear Tower", "Firespitter",
            "Super Wizard Tower", "Revenge Tower"]
TRAPS = ["Bomb", "Spring Trap", "Air Bomb", "Giant Bomb", "Seeking Air Mine", "Skeleton Trap", "Tornado Trap",
         "Giga Bomb"]
RESOURCE_BUILDINGS = ["Gold Mine", "Elixir Collector", "Dark Elixir Drill", "Gold Storage", "Elixir Storage",
             "Dark Elixir Storage", "Clan Castle"]
ARMY = ["Laboratory", "Army Camp", "Barracks", "Dark Barracks", "Spell Factory", "Dark Spell Factory", "Workshop",
        "Pet House", "Blacksmith", "Hero Hall", "Crafting Station"]
HEROES = ["Barbarian King", "Archer Queen", "Minion Prince", "Grand Warden", "Royal Champion", "Dragon Duke"]
CATALOG = TOWN_HALL + ARMY + DEFENSES + RESOURCE_BUILDINGS + TRAPS + HEROES
GROUP = {**{n: "Town Hall" for n in TOWN_HALL}, **{n: "Defense" for n in DEFENSES}, **{n: "Trap" for n in TRAPS},
         **{n: "Resources" for n in RESOURCE_BUILDINGS}, **{n: "Army" for n in ARMY}, **{n: "Hero" for n in HEROES}}
SAME = 0.85                 # an OCR'd name this close to a listed one is that one


def _panel(frame):
    """The open Build panel's X, or None."""
    return vision.find(frame, "build/close")


def open_panel(bot):
    """The Build panel, open. Returns its X."""
    if not go_home(bot):
        raise BotError("Not on the home village")
    m = bot.find("home/build_button")
    if not m:
        raise BotError("No Build button on the village")
    bot.tap_match(m)
    x = bot.wait("build/close", 4, interval=0.25)
    if not x:
        raise BotError("The Build panel did not open")
    bot.sleep(0.4)                                   # the list slides in
    return x


def close_panel(bot):
    m = _panel(bot.shot())
    if m:
        bot.tap_match(m, jitter=2)
        bot.sleep(0.5)


def builders(frame, x):
    """(free, all) builders from the panel's first tab ("1/7"); None when it cannot be read."""
    left = x.x - PANEL_LEFT
    for t, _, (bx, _, _, _) in vision.text_reader.read(frame, (left, x.y + TABS, PANEL_LEFT + 25, 90)):
        m = re.fullmatch(r"(\d)\s*/\s*(\d)", t.strip().replace("I", "1").replace("l", "1"))
        if m and bx < left + 110:
            return int(m.group(1)), int(m.group(2))
    return None


def _resource(frame, x, y):
    """The resource of the icon at (x, y): gold (yellow), elixir (pink) or dark (dark); None when unsure."""
    patch = cv2.cvtColor(frame[max(0, y - 4):y + 5, max(0, x - 4):x + 5], cv2.COLOR_BGR2HSV).reshape(-1, 3)
    if not len(patch):
        return None
    hue, sat, val = (float(v) for v in patch.mean(0))
    if val < 130:
        return "dark"
    if 15 <= hue <= 35 and sat > 120:
        return "gold"
    if 135 <= hue <= 175 and sat > 80:
        return "elixir"
    return None


def _seconds(text):
    """ "2d14H" / "6H19M" / "45s" -> seconds; None when it is not a time."""
    t = text.lower().replace(" ", "").replace("o", "0")
    t = re.sub(r"[s](?=[dhm])", "5", re.sub(r"[il](?=[dhm0-9])", "1", t))      # "SH29M" = 5h 29m
    m = re.fullmatch(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", t)
    if not m or not any(m.groups()):
        return None
    d, h, mi, se = (int(g or 0) for g in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + se


def soonest_done(frame, x):
    """Seconds until the first upgrade in progress is done (the times above "Suggested upgrades" at the top of the
    list); None when none is read."""
    left = x.x - PANEL_LEFT
    lines = vision.text_reader.read(frame, (left, x.y + ROWS_TOP, PANEL_LEFT + 20, ROWS_BOTTOM - ROWS_TOP))
    header = min((by for t, _, (bx, by, bw, bh) in lines if "suggested" in t.lower()), default=None)
    if header is None:
        return None
    times = [_seconds(t) for t, _, (bx, by, bw, bh) in lines if by < header and bx > left + COST_X]
    times = [t for t in times if t]
    return min(times) if times else None


def read_rows(frame, x):
    """The upgrades the panel lists now: [{"name", "cost", "res", "y"}] top to bottom (rows in progress have no
    cost and are left out)."""
    left = x.x - PANEL_LEFT
    lines = vision.text_reader.read(frame, (left, x.y + ROWS_TOP, PANEL_LEFT + 20, ROWS_BOTTOM - ROWS_TOP))
    names = [(t, by + bh // 2) for t, c, (bx, by, bw, bh) in lines        # (not the row's lightning icons)
             if bx < left + NAME_X + 40 and c > 0.5 and len(re.findall(r"[A-Za-z]", t)) >= 3]
    rows = []
    for t, c, (bx, by, bw, bh) in lines:
        digits = re.sub(r"[\s.,]", "", t)
        if bx < left + COST_X or not digits.isdigit() or int(digits) < 100:
            continue
        cy = by + bh // 2
        above = [(ny, n) for n, ny in names if 8 <= cy - ny <= 40]    # the name: the row's first line, above the cost
        if not above:
            continue
        rows.append({"name": max(above)[1].strip(), "cost": int(digits), "res": _resource(frame, bx + bw + 13, cy),
                     "y": cy - 10})
    return rows


def _span(secs):
    secs = int(secs)
    return f"{secs // 86400}d {secs // 3600 % 24}h" if secs >= 86400 else f"{secs // 3600}h {secs // 60 % 60}m"


def _norm(name):
    return re.sub(r"[^a-z]", "", name.lower())


def key(name):
    """A building's name to compare: "INfeRNO TOWeR x 3" / "ElixiR CollectoR XS" -> "infernotower" /
    "elixircollector" (the count after it goes, letters only)."""
    return _norm(re.sub(r"\s*[x×]\s*[0-9sSoOlI]{1,2}\s*$", "", name.strip()))


UNTICKED = TOWN_HALL + HEROES     # not upgraded unless you tick them: a Town Hall changes what "full" is (its
#                                   level in Accounts), a hero cannot fight while it upgrades


def plan(s):
    """Your list from the settings, completed with the buildings it does not name yet (at its end; the Town Hall and
    heroes unticked): [(name, ticked)] in your order."""
    saved = [(str(e["name"]).strip(), bool(e.get("on", True))) for e in s.get("list", []) if str(e.get("name", ""))]
    have = {key(n) for n, _ in saved}
    heroes = bool(s.get("heroes", False))           # (older settings: one switch for all heroes)
    return saved + [(n, heroes if n in HEROES else n not in UNTICKED) for n in CATALOG if key(n) not in have]


def listed(name, keys):
    """The index in your list of the building this row is (keys: the list's key()s), or None."""
    k = key(name)
    if k in keys:
        return keys.index(k)
    best = max(range(len(keys)), key=lambda i: difflib.SequenceMatcher(None, k, keys[i]).ratio(), default=None)
    if best is not None and difflib.SequenceMatcher(None, k, keys[best]).ratio() >= SAME:
        return best
    return None


def _payable(row, res, s):
    """Can this row be paid now, with a resource the settings let it spend (and keeping what they keep)?"""
    r = row["res"]
    if r is None or not s.get("spend", {}).get(r, True):
        return False
    have = res.get(r)
    keep = int(s.get("keep", {}).get(r, 0) or 0)
    return have is not None and have - keep >= row["cost"]


def choices(rows, res, s, entries, tried=()):
    """The rows that may be upgraded now and can be paid: [(rank, row)] - rank = place in your list (a name not in
    it: after the list, and only in the game's order)."""
    keys = [key(n) for n, _ in entries]
    out = []
    for row in rows:
        k = key(row["name"])
        if k in tried or "wall" in k:                # walls: their own window (not handled)
            continue
        i = listed(row["name"], keys)
        if i is None:
            if s.get("order", "game") == "mine":
                continue
            rank = len(entries)
        elif not entries[i][1]:
            continue
        else:
            rank = i
        if _payable(row, res, s):
            out.append((rank, row))
    return out


def _green(frame, box):
    """A plain part of a button is green (the Confirm that pays with resources, not the grey magic item)."""
    x, y, w, h = box
    patch = cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2HSV).reshape(-1, 3)
    return len(patch) > 0 and 30 <= float(patch[:, 0].mean()) <= 75 and float(patch[:, 1].mean()) > 90


def _shows(text, cost):
    """The Confirm's text shows this cost ("13 000 000", the coin after it sometimes read as one more 0)."""
    digits, want = re.sub(r"\D", "", text), str(cost)
    return digits == want or (digits.startswith(want) and len(digits) == len(want) + 1)


BUSY_X = (329, -7)          # the X of the "Hey Chief! ... all your Builders are busy" box, from its title


def _blocked(frame):
    """A box or window over the panel: the builders-busy box (its gem buttons are never tapped) or an upgrade
    window."""
    return vision.find(frame, "upgrade/builders_busy") or vision.find(frame, "upgrade/close")


def _close_busy(bot, m):
    """Close the "all your Builders are busy" box with its X - never its gem buttons."""
    k = m.box[2] / vision.templates.image("upgrade/builders_busy").shape[1]
    bot.tap(int(m.x + BUSY_X[0] * k), int(m.y + BUSY_X[1] * k), jitter=2)
    bot.sleep(0.6)


def _scroll(bot, x):
    """The list one page further down. Returns False at its end (nothing moved)."""
    left = x.x - PANEL_LEFT
    area = (slice(x.y + ROWS_TOP, x.y + ROWS_BOTTOM), slice(left, x.x + 20))
    before = bot.shot()[area].astype("int16")
    cx = x.x - PANEL_LEFT // 2
    bot.swipe((cx, x.y + 670), (cx, x.y + 220), 600)    # held at the end: the list stops where the finger stops
    bot.sleep(0.6)
    return float(abs(bot.shot()[area].astype("int16") - before).mean()) > 2


def choose(bot, x, frame, res, s, entries, tried):
    """The row to upgrade, on screen: (row, panel X) or (None, X).
    The game's order: the first row that may be upgraded and can be paid, scrolling down only until one shows.
    Your order: the whole list is read, the best one is found, and the list is opened again at its page."""
    mine = s.get("order", "game") == "mine"
    best, page = None, 0
    for scroll in range(SCROLLS + 1):
        found = choices(read_rows(frame, x), res, s, entries, tried)
        if found and not mine:
            return found[0][1], x
        for rank, row in found:
            if best is None or rank < best[0]:
                best, page = (rank, row), scroll
        if scroll == SCROLLS or not _scroll(bot, x):
            break
        frame = bot.shot()
    if best is None:
        return None, x
    if page == scroll:                               # still on screen
        return best[1], x
    close_panel(bot)
    x = open_panel(bot)                              # opens at the top: the same page drags reach it again
    for _ in range(page):
        _scroll(bot, x)
    want = key(best[1]["name"])
    again = [r for r in read_rows(bot.shot(), x) if key(r["name"]) == want]
    if not again:
        log.info("Upgrade: %s was not found again on its page", best[1]["name"])
        tried.add(want)
        return None, x
    return again[0], x


def _confirm(bot, row):
    """The row's upgrade window is open: tap its green Confirm when it shows exactly the row's cost. Returns
    "started", "busy" (the game says every builder is busy: closed with its X) or None (not started)."""
    m = bot.wait("upgrade/confirm", 4, interval=0.25)
    if not m:
        log.info("Upgrade: the window of %s did not open", row["name"])
        return None
    bot.sleep(0.3)
    f = bot.shot()
    m = vision.find(f, "upgrade/confirm") or m
    k = m.box[2] / vision.templates.image("upgrade/confirm").shape[1]      # the window's size (BlueStacks: x0.833)
    cost_box = (int(m.x - 150 * k), int(m.y + 18 * k), int(300 * k), int(55 * k))
    text, _ = vision.text_reader.read_line(f, cost_box)
    margin = (int(m.x - 125 * k), int(m.y), int(25 * k), int(35 * k))     # the button's plain left part
    tap = (m.x, int(m.y + 45 * k))
    if not _shows(text, row["cost"]) or not _green(f, margin):
        log.warning("Upgrade: %s - the Confirm shows %s, not %s: not tapped", row["name"], text.strip() or "?",
                    f"{row['cost']:,}")
        bot.save_error("upgrade-confirm", f)
        _close_window(bot)
        return None
    bot.tap(*tap, jitter=3)
    # the window closes when the upgrade starts; the builders-busy box comes within half a second instead
    end, gone = time.monotonic() + 4, None
    while time.monotonic() < end:
        control.sleep(0.3)
        f = bot.shot()
        busy = vision.find(f, "upgrade/builders_busy")
        if busy:
            _close_busy(bot, busy)
            return "busy"
        if vision.find(f, "upgrade/close"):
            gone = None
        elif gone is None:
            gone = time.monotonic()
        elif time.monotonic() - gone >= 1.5:
            return "started"
    log.warning("Upgrade: the window of %s stayed open after Confirm - closed, nothing paid", row["name"])
    bot.save_error("upgrade-after-confirm")
    _close_window(bot)
    return None


def _close_window(bot):
    m = bot.find("upgrade/close")
    if m:
        bot.tap_match(m, jitter=2)
        bot.sleep(0.6)


def spend(bot, account):
    """Start as many upgrades as there are free builders and loot to pay them. Returns the number started.
    The builders' tab ("1/7") counts the Goblin Builder too (paid with gems, never used), so the game's "all your
    Builders are busy" box is the answer; then the account is not looked at again until its first upgrade in
    progress is done. At the end the storages are read again, so what was really spent is in the log."""
    s = bot.settings.get("upgrade", {})
    name = account["name"]
    busy = bot.state.setdefault("builders_busy", {})
    left = busy.get(name, 0) - time.time()
    if left > 0:
        log.info("%s: every builder is busy for another %s", name, _span(left))
        return 0
    if not go_home(bot):
        raise BotError("Not on the home village")
    bot.action = "Upgrade: reading storages"
    before = loot.home_resources(bot)
    res = dict(before)
    entries = plan(s)
    x = open_panel(bot)
    started, tried, paid = 0, set(), {}
    try:
        while True:
            control.checkpoint()
            frame = bot.shot()
            m = _blocked(frame)
            if m:                                    # never tap a row through a box or window
                if vision.find(frame, "upgrade/builders_busy"):
                    _close_busy(bot, m)
                else:
                    _close_window(bot)
                frame = bot.shot()
                if _blocked(frame):
                    raise BotError("A box stays open over the Build panel")
            free = builders(frame, x)
            if free is None:
                log.info("%s: the free builders could not be read - no upgrade", name)
                bot.save_error("upgrade-builders", frame)
                break
            if free[0] == 0:                         # (the tab counts as builders start, and the Goblin Builder)
                log.info("%s: no free builder", name)
                break
            bot.action = "Upgrade: choosing"
            row, x = choose(bot, x, frame, res, s, entries, tried)
            if row is None:
                log.info("%s: no upgrade from your list it can pay now (%s)", name, loot._fmt(res))
                break
            tried.add(key(row["name"]))
            bot.action = f"Upgrade: {row['name']}"
            log.info("%s: upgrading %s for %s %s", name, row["name"], f"{row['cost']:,}", row["res"])
            bot.tap(x.x - PANEL_LEFT + 160, row["y"], jitter=4)
            got = _confirm(bot, row)
            if got == "busy":
                close_panel(bot)
                x = open_panel(bot)                  # at the top again: the upgrades in progress
                wait = soonest_done(bot.shot(), x) or 1800
                busy[name] = time.time() + wait
                config.save_state(bot.state)
                log.info("%s: the game says every builder is busy - next look in %s (the first upgrade in progress "
                         "is done then)", name, _span(wait))
                break
            if got == "started":
                started += 1
                res[row["res"]] -= row["cost"]
                paid[row["res"]] = paid.get(row["res"], 0) + row["cost"]
                bot.stats["upgrades"] = bot.stats.get("upgrades", 0) + 1
                log.info("%s: %s upgrade started", name, row["name"])
            bot.sleep(0.6)
            x = _panel(bot.shot()) or open_panel(bot)    # (the panel stays open behind the window)
    finally:
        close_panel(bot)
        go_home(bot)
    if started:
        after = loot.home_resources(bot)
        drop = {r: (before.get(r) or 0) - (after.get(r) or 0) for r in paid}
        log.info("%s: %d upgrade(s) started; storages %s -> %s", name, started, loot._fmt(before), loot._fmt(after))
        if any(drop[r] < paid[r] // 2 for r in paid):
            log.warning("%s: the storages did not drop as much as the upgrades cost - check the game", name)
            bot.save_error("upgrade-not-paid")
    p = bot.progress.setdefault(name, {})
    p["upgrades"] = p.get("upgrades", 0) + started
    return started
