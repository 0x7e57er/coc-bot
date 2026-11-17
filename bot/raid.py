"""Clan Capital Raid Weekend: each ticked account uses its raid attacks on the enemy's Clan Capital.

Raid Weekend runs from Friday 07:00 to Monday 07:00 UTC (12:30 India time). An account has 5 raid attacks
(6 with the bonus); how many are left shows as a red badge ("5 ⚔") over the Clan Capital airship and over
the Raid Map button. One raid attack:

  the village, zoomed out and moved so the airship shows -> the airship -> the clan's Capital (popups
  closed) -> on the account's first raid attack: the army set to Super Miners, 1 Frost and 2 Graveyard
  (Save) -> Raid Map -> the district to attack is tapped: its bar's Attack is red while the district is not
  destroyed (grey when it is: the bar is closed by tapping an empty spot and the next district is tapped)
  -> Attack -> zoomed out and moved fully down and right, so each district's free deploy area is always at
  the same place -> all the miners on it, the spells into the district -> the game is closed and opened
  again with ADB (the battle goes on by itself: no waiting for it) -> the next raid attack.

The bot remembers in config/state.json: where each district is on the raid map, the deploy spot of each
district (found once from the lit deploy area, then tapped straight away), the district it attacks this
weekend (the next attack goes straight there) and the accounts that have no raid attack left.
"""

import datetime as dt
import difflib
import logging
import re
import time

import cv2
import numpy as np

from . import config, states, vision
from .context import BotError
from .control import control
from .space import space
from .states import go_home

log = logging.getLogger("bot")

UTC = dt.timezone.utc
START = (4, 7)                     # Friday (weekday 4) 07:00 UTC
LENGTH = dt.timedelta(days=3)      # to Monday 07:00 UTC

# the districts in the order they are tried: from the top of the raid map down (the last ones are on screen after
# swiping the map up); Capital Peak opens when all the others are destroyed.
ORDER = ["Barbarian Camp", "Wizard Valley", "Dragon Cliffs", "Balloon Lagoon", "Builder's Workshop",
         "Golem Quarry", "Goblin Mines", "Skeleton Park", "Capital Peak"]
LABEL_TO_HALL = 78                 # a district's hall is this far under its name label (battlefield px)
BAR_ATTACK = (1045, 960, 120, 35)  # the district bar's Attack button (red = can attack, grey = destroyed)
NOTICE = (470, 220, 990, 120)      # the game's red notice at the top of the raid map
DIALOGS = ("raid/attack_now_title", "raid/attack_go")   # centred popups: looked for on the whole screen
EMPTY = (1650, 400)                # an empty spot of the raid map (closes a district's bar)

# the capital army: (card in Change Capital Army, taps) - as many Super Miners as fit, 1 Frost, 2 Graveyard
ARMY = [("raid/unit_super_miner", 12), ("raid/spell_frost", 1), ("raid/spell_graveyard", 2)]

# In a raid battle the game lights up where troops can go: a pale green veil with a white outline - strips along
# the district's edges, and every part of it already destroyed. The land of a district never changes, so with the
# camera at a fixed place a district's deploy spot is too: it is found once and remembered.
ZOOM_PRESSES = 3                   # zoomed out completely (one more press than in the village, to be sure)
PAN = ((1466, 784), (623, 268))    # the finger goes up and left: the camera moves down and right ...
PAN_SWIPES = 3                     # ... until it stops at the battlefield's corner
LIT = ((42, 80, 168), (62, 135, 220))          # the lit area on grass (hue, saturation, value), from Dragon Cliffs
LIT_LOOSE = ((35, 50, 150), (80, 140, 235))    # a second look: other ground under the veil
ZONE_MIN = 400                     # a lit patch smaller than this (game-space px) is a flower bed or a tree top
ZONE_DEPTH = 7                     # a spot is at least this far inside the lit area (battlefield px)
ZONE_GAP = 70                      # the spots tried one after another are this far apart (battlefield px)
ZONE_BAR = 880                     # the card bar starts here (base y): no spot below it
ZONE_UI = [(0, 0, 480, 260), (760, 0, 400, 120), (1440, 0, 480, 230), (0, 740, 280, 140),
           (1560, 720, 360, 160)]  # name and loot, timer, resources, Surrender, damage: never a spot
# Nothing lit took the miners: spots around the middle of the screen are tried one by one (with the camera in the
# battlefield's corner the district's lower-right edge runs near it)
PROBE_STEP = 90                    # battlefield px between them
PROBES = 16
INTO = (400, 250)                  # a battlefield point inside the district: up and left (the camera is at its
#                                    lower-right corner)
SPELL_IN = 150                     # the spells go this far from the miners' spot into the district
CARD_FIND = 0.75                   # a selected card has a white rim and sits higher: it matches less well
MINER_TAPS = 12                    # taps when the "x10" on the miner card cannot be read
BATTLE_CARDS = [("raid/battle_frost", 1), ("raid/battle_graveyard", 2)]
CLOSE_AFTER = 1.0                  # seconds from the last deploy to closing the game (the taps reach the server)

# ----------------------------------------------------------------------------- the weekend and memory
def window(now=None):
    """(active, start, end) of the current Raid Weekend, or of the next one when none is on."""
    now = now or dt.datetime.now(UTC)
    day, hour = START
    start = (now - dt.timedelta(days=(now.weekday() - day) % 7)).replace(hour=hour, minute=0, second=0,
                                                                         microsecond=0)
    if start > now:
        start -= dt.timedelta(days=7)
    end = start + LENGTH
    if now < end:
        return True, start, end
    start += dt.timedelta(days=7)
    return False, start, start + LENGTH


def describe_window(now=None):
    """'Raid Weekend: 1d 4h left' / 'Next Raid Weekend in 2d 3h' (for the log and the window)."""
    now = now or dt.datetime.now(UTC)
    active, start, end = window(now)
    left = (end if active else start) - now
    text = f"{left.days}d {left.seconds // 3600}h" if left.days else f"{left.seconds // 3600}h " \
                                                                      f"{left.seconds % 3600 // 60}m"
    return active, (f"Raid Weekend on: {text} left" if active else f"Next Raid Weekend in {text}")


def _weekend(bot):
    """This weekend's memory: {"done": {account: True}, "next": district}. An older weekend's is dropped."""
    key = window()[1].strftime("%Y-%m-%d")
    slot = bot.state.get("raid")
    if not isinstance(slot, dict) or slot.get("weekend") != key:
        slot = bot.state["raid"] = {"weekend": key, "done": {}, "next": ORDER[0]}
    return slot


def pending(bot, name):
    """True while this account may still have raid attacks this weekend (as far as the bot knows)."""
    return not _weekend(bot)["done"].get(name)


def _memory(bot, kind):
    """What was learned for this screen size: "raid_map" (district -> [x, y, view]) or "raid_spots"
    (district -> [x, y]); the same points on every enemy Capital."""
    native = space.native or (1920, 1080)
    return bot.state.setdefault(f"{kind}_{native[0]}x{native[1]}", {})


def _save(bot):
    config.save_state(bot.state)


# ----------------------------------------------------------------------------- the village
def _badges(frame):
    """Red badges like the airship's "5 ⚔" (a rounded red box): [(x, y, w, h)]. The badge hangs over the
    village, so its size goes with the village's (and a little with how far the zoom went out)."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = (((hsv[:, :, 0] < 7) | (hsv[:, :, 0] > 173)) & (hsv[:, :, 1] > 150) & (hsv[:, :, 2] > 140)).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if space.f(44) <= w <= space.f(80) and space.f(32) <= h <= space.f(56) and a / (w * h) > 0.6 \
                and space.s(200) < y < space.s(1000) and space.s(150) < x < space.s(1500):
            out.append((int(x), int(y), int(w), int(h)))
    return out


def _digits(text):
    """The number in a short OCR'd text, with the usual letter/digit mix-ups fixed (or None)."""
    for a, b in (("S", "5"), ("s", "5"), ("l", "1"), ("I", "1"), ("O", "0"), ("o", "0")):
        text = text.replace(a, b)
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


# Where the airship is depends on the village's scenery: the village is zoomed out and swiped towards each of
# these corners in turn (finger from -> to, battlefield points) until its red badge shows.
VIEWS = [((900, 800), (1100, 350)),       # the river at the lower left (the first scenery it was seen in)
         ((900, 800), (1100, 470)),
         ((1100, 800), (800, 350)),       # lower right
         ((900, 350), (1100, 800)),       # upper left
         ((1100, 350), (800, 800))]       # upper right


def _show_airship(bot, view):
    """The home village zoomed out and swiped to one of VIEWS. Returns the frame."""
    if not go_home(bot, 30):
        raise BotError("Not on the home village")
    bot.device.zoom_out()
    control.sleep(0.4)
    a, b = VIEWS[view]
    bot.swipe(space.center(*a), space.center(*b), 600)
    control.sleep(1.0)
    return bot.shot()


def find_airship(bot, name):
    """The airship's tap point and the raid attacks its badge shows; (None, 0) when no badge shows in any view (no
    raid attack left - or the airship was not seen). The badge is found by colour and shape (the same in every
    scenery; the airship looks different in each). Where it was is remembered for this account: that view is looked
    at first, and with no badge seen its spot is tapped once more (the Capital's Raid Map badge has the last word)."""
    learned = _memory(bot, "raid_airship").get(name)
    views = list(range(len(VIEWS)))
    if learned:
        views.remove(learned[2])
        views.insert(0, learned[2])
    for view in views:
        f = _show_airship(bot, view)
        found = _badges(f)
        log.debug("Raid: %s - airship view %d: %d red badge(s)", name, view + 1, len(found))
        if found:
            x, y, w, h = max(found, key=lambda b: b[1])      # the lowest one: the airship is under its badge
            text, _ = vision.text_reader.read_line(f, (x + space.s(4), y + space.s(2), w // 2, h - space.s(6)))
            left = _digits(text)
            tap = (x + w // 2, y + h + int(space.f(75)))
            _memory(bot, "raid_airship")[name] = [tap[0], tap[1], view]
            log.info("Raid: %s - airship found (view %d), its badge says %s attack(s)", name, view + 1,
                     left if left and left <= 6 else "some")
            return tap, (left if left and left <= 6 else 1)
    if learned:
        log.info("Raid: %s - no airship badge seen; tapping where the airship was last time to make sure", name)
        _show_airship(bot, learned[2])
        return tuple(learned[:2]), 0
    log.info("Raid: %s - no airship badge in any of %d views: no raid attack left (or the airship is out of "
             "sight)", name, len(VIEWS))
    bot.save_error("raid-no-airship")
    return None, 0

# ----------------------------------------------------------------------------- the Capital
def _find(frame, key):
    if key in DIALOGS:
        return vision.find(frame, key, region=(0, 0, frame.shape[1], frame.shape[0]))
    return vision.find(frame, key)


def _dismiss(bot, frame):
    """A popup over the Capital (news, rewards, the game's dark dialogs): closed. True if one was."""
    box = states.dialog_box(frame)
    if box is not None:
        return states.system_dialog(bot, frame, box)
    full = (0, 0, frame.shape[1], frame.shape[0])
    for key in ("popup/close_x", "upgrade/close", "popup/continue_green", "settings/close", "army/close"):
        if vision.templates.has(key):
            m = vision.find(frame, key, region=full, threshold=0.8)
            if m:
                bot.tap_match(m, jitter=2)
                control.sleep(0.6)
                return True
    return False


def _wait_any(bot, keys, timeout, dismiss=False):
    """The first of `keys` on screen within `timeout` (popups closed meanwhile when `dismiss`), or None."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        f = bot.shot()
        for k in keys:
            if vision.templates.has(k) and _find(f, k):
                return k
        if dismiss and _dismiss(bot, f):
            continue
        control.sleep(0.4)
    return None


def _red_share(frame, region):
    """How much of a game-space region is bright red (badges, the Attack button)."""
    x, y, w, h = region
    p = cv2.cvtColor(frame[max(0, y):y + h, max(0, x):x + w], cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(int)
    if not len(p):
        return 0.0
    return float((((p[:, 0] < 8) | (p[:, 0] > 172)) & (p[:, 1] > 120) & (p[:, 2] > 120)).mean())


def _red(frame, box):
    return _red_share(frame, space.region(*box)) > 0.3


CAPITAL = ["raid/capital_title", "raid/attacking_title", "raid/next_raid"]


NEW_RAID_GO = 127      # the "New Raid" banner's Go is this far under its title (game px)


def open_capital(bot, tap):
    """Tap the airship; popups in the Capital are closed. Returns the screen that opened: the clan's own
    Capital ("raid/capital_title"), the raid map ("raid/attacking_title"), the last raid's summary
    ("raid/next_raid") or None. A tap that missed the airship (the village is still there a few seconds later)
    gives None at once; the "New Raid" banner of a raid that just began is passed with its Go."""
    bot.tap(*tap, jitter=3)
    end, village = time.monotonic() + 25, 0
    while time.monotonic() < end:
        control.sleep(0.5)
        f = bot.shot()
        banner = vision.find(f, "raid/new_raid")
        if banner:
            log.info("Raid: a new raid has begun - Go")
            bot.tap(banner.x, banner.y + int(space.s(NEW_RAID_GO)), jitter=4)
            control.sleep(1.5)
            continue
        for key in CAPITAL:
            if _find(f, key):
                return key
        if vision.find(f, "home/build_button"):
            village += 1
            if village >= 8:                          # 4 s on the village: the tap missed the airship
                log.info("Raid: the tap did not open the Clan Capital (still on the village)")
                bot.save_error("raid-missed-airship", f)
                return None
            continue
        village = 0
        _dismiss(bot, f)
    return None


def attacks_left(frame):
    """Raid attacks left: the number on the red badge over Raid Map / Raid Info (bottom right); 0 when there
    is no badge, None when neither button is on screen."""
    m = vision.find(frame, "raid/raid_map") or vision.find(frame, "raid/raid_info")
    if not m:
        return None
    if _red_share(frame, (m.x - space.s(70), m.y - space.s(165), space.s(140), space.s(55))) < 0.3:
        return 0
    text, _ = vision.text_reader.read_line(frame, (m.x - space.s(45), m.y - space.s(160), space.s(50),
                                                   space.s(45)))
    left = _digits(text)
    return left if left and left <= 6 else 1


def _card(frame, key):
    """A card that can still be used: found, and in colour - a full army greys the cards of the unit list,
    and a used-up card of the battle bar turns grey (grey ~10, the pale Frost card ~58)."""
    m = vision.find(frame, key)
    if not m:
        return None
    x, y, w, h = m.box
    return m if cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2HSV)[:, :, 1].mean() > 30 else None


def _scale_of(m, key):
    """How big a match is drawn relative to its picture (BlueStacks draws some windows smaller)."""
    return m.box[2] / vision.templates.image(key).shape[1]


def set_army(bot):
    """Change Capital Army (the button bottom left of the Capital): already Super Miners, 1 Frost and 2
    Graveyard -> Cancel; else the army deleted, then Super Miners only (as many as fit), 1 Frost and 2
    Graveyard, Save. True when the army is right; when a card is missing the window is cancelled and the army
    stays as it was."""
    title = None
    for _ in range(3):                  # a tap while the Capital is still flying in is lost: again
        if not bot.tap_template("raid/army_button", timeout=5):
            break
        title = bot.wait("raid/army_title", 5)
        if title:
            break
    if not title:
        bot.save_error("raid-army-window")
        return False
    k = _scale_of(title, "raid/army_title")

    def at(dx, dy):
        return title.x + int(space.s(dx) * k), title.y + int(space.s(dy) * k)

    cancel = at(30, 331)
    rx, ry = at(-640, 72)
    ready = (rx, ry, int(space.s(580) * k), int(space.s(205) * k))      # the army's row
    if vision.find(bot.shot(), "raid/army_ready", region=ready):
        log.info("Raid army: already Super Miners, 1 Frost, 2 Graveyard")
        bot.tap(*cancel, jitter=3)
        return bot.wait_gone("raid/army_title", 5)
    if bot.find("raid/army_trash"):                          # red while the army has units
        bot.tap_template("raid/army_trash", timeout=2, after=0.5)
    for _ in range(2):         # the unit list (under the buttons) starts with Super Barbarian: swiped to its
        bot.swipe(at(450, 610), at(-450, 610), 300)          # end, where the Super Miner and the spells are
        control.sleep(0.3)
    control.sleep(0.3)
    for key, taps in ARMY:
        m = _card(bot.shot(), key)
        if not m:
            log.warning("Raid army: no %s to add (not unlocked in this clan?) - the army is left as it was",
                        key.split("/")[1].replace("_", " "))
            bot.save_error("raid-army")
            bot.tap(*cancel, jitter=3)
            bot.wait_gone("raid/army_title", 5)
            return False
        bot.tap_burst(m, taps, interval=0.08)
        control.sleep(0.3)
    bot.tap_template("raid/army_save", timeout=3)
    return bot.wait_gone("raid/army_title", 6)


def open_raid_map(bot):
    """From the clan's own Capital to the raid map (past the summary of the last raid). True when it is on
    screen."""
    if not bot.tap_template("raid/raid_map", timeout=3):
        return False
    key = _wait_any(bot, ["raid/attacking_title", "raid/next_raid"], 15, dismiss=True)
    if key == "raid/next_raid":
        bot.tap_template("raid/next_raid", timeout=3)
        key = _wait_any(bot, ["raid/attacking_title"], 15, dismiss=True)
    return key == "raid/attacking_title"


# ----------------------------------------------------------------------------- the raid map
def _norm(text):
    return re.sub(r"[^a-z]", "", text.lower())


def _name_of(text):
    """The district a label reads as (OCR mix-ups allowed), or None."""
    t = _norm(text)
    if len(t) < 5:
        return None
    ratio, name = max((difflib.SequenceMatcher(None, t, _norm(n)).ratio(), n) for n in ORDER)
    return name if ratio >= 0.75 else None


def _tappable(x, y):
    """On screen and not under the raid map's buttons (Map and army bottom left, Raid Info bottom right)."""
    if not (0 < x < space.w and 0 < y < space.h - space.s(40)):
        return False
    return not (y > space.h - space.s(240) and (x < space.s(340) or x > space.w - space.s(340)))


def read_map(frame):
    """The districts on screen: {name: {"hall": (x, y) to tap, or None when off screen / under a button,
    "pct": destruction % or None, "locked": bool}}, from their name labels and the "0%" / "Locked" over
    them."""
    texts = vision.text_reader.read(frame, (space.s(300), space.s(140), space.w - space.s(600),
                                            space.h - space.s(140)))
    out = {}
    for text, _, (x, y, w, h) in texts:
        name = _name_of(text)
        if not name or name in out:
            continue
        above = [t for t, _, (tx, ty, tw, th) in texts if y - space.s(50) <= ty < y and tx < x + w and tx + tw > x]
        pct = next((_digits(t[:t.index("%")]) for t in above if "%" in t and _digits(t[:t.index("%")]) is not None),
                   None)
        hall = (x + w // 2, y + h + int(space.f(LABEL_TO_HALL)))
        out[name] = {"hall": hall if _tappable(*hall) else None, "pct": pct,
                     "locked": any("lock" in t.lower() for t in above)}
    return out


def _scroll(bot, down):
    """Swipe the raid map to its bottom (the finger goes up: the last four districts) or back to its top."""
    a, b = space.center(960, 880), space.center(960, 230)
    for _ in range(2):
        bot.swipe(a if down else b, b if down else a, 450)
        control.sleep(0.3)
    control.sleep(0.6)


def _close_bar(bot):
    """Tap an empty spot of the map: the district's bar (Scout / Attack) slides away."""
    bot.tap(*space.center(*EMPTY), jitter=3)
    control.sleep(0.5)


def _bar_name(frame, bar):
    """The district named on the bar under a tapped district (bar = its Scout button)."""
    text, _ = vision.text_reader.read_line(frame, (bar.x - space.s(365), bar.y + space.s(8), space.s(245),
                                                   space.s(42)))
    return _name_of(text)


def _try(bot, name, point):
    """Tap a district: "attack" when its bar opened with a red Attack (left open), "done" when Attack is grey
    (destroyed: the bar is closed), None when the tap did not open this district's bar."""
    bot.tap(*point, jitter=4)
    bar, f = None, None
    for _ in range(4):                               # the bar slides in
        control.sleep(0.5)
        f = bot.shot()
        bar = vision.find(f, "raid/district_bar")
        if bar:
            break
    if not bar:
        log.debug("Raid: tapping %s at %d, %d opened no bar", name, *point)
        return None
    seen = _bar_name(f, bar)
    if seen != name:
        log.debug("Raid: tapping %s opened %s's bar", name, seen or "another district")
        _close_bar(bot)
        return None
    if _red(f, BAR_ATTACK):
        return "attack"
    _close_bar(bot)
    return "done"


def _summary(seen):
    return ", ".join(f"{n} {'locked' if d['locked'] else '?' if d['pct'] is None else str(d['pct']) + '%'}"
                     for n, d in seen.items()) or "no district read"


def choose_district(bot):
    """Tap the district to attack, from what the raid map shows: its labels say each district's destruction
    ("100%" = destroyed) and "Locked". Districts already being attacked (1-99 %) come first, then the others from
    Barbarian Camp on (the one attacked last first); destroyed and locked ones are never tapped. The map is read at
    its top, then swiped to its bottom for the districts not seen. A district whose label cannot be tapped is tried
    where it was found before. Returns its name with its bar open (Attack is red), or None when none can be
    attacked now."""
    memory = _memory(bot, "raid_map")
    week = _weekend(bot)
    first = week.get("next") if week.get("next") in ORDER else ORDER[0]
    i = ORDER.index(first)
    rotation = [n for n in ORDER[i:] + ORDER[:i] if n != "Capital Peak"] + ["Capital Peak"]
    done, tried = set(), set()
    for view in ("top", "low"):
        control.checkpoint()
        if view == "low":
            _scroll(bot, down=True)
        seen = read_map(bot.shot())
        log.info("Raid map (%s): %s", view, _summary(seen))
        for name, d in seen.items():
            if d["locked"] or (d["pct"] or 0) >= 100:
                done.add(name)
        order = sorted((n for n in rotation if n in seen and n not in done and n not in tried),
                       key=lambda n: (not 0 < (seen[n]["pct"] or 0) < 100, rotation.index(n)))
        for name in order:
            control.checkpoint()
            d = seen[name]
            known = memory.get(name)
            points = ([d["hall"]] if d["hall"] else []) + ([tuple(known[:2])] if known and known[2] == view else [])
            if not points:
                continue                             # under a button here: maybe in the other view
            tried.add(name)
            log.info("Raid: trying %s (%s)", name, "not read" if d["pct"] is None else f"{d['pct']}% destroyed")
            got = None
            for point in points:
                got = _try(bot, name, point)
                if got:
                    memory[name] = [point[0], point[1], view]
                    break
            if got == "attack":
                if week.get("next") != name:
                    log.info("Raid: next district %s", name)
                week["next"] = name
                _save(bot)
                return name
            if got == "done":
                log.info("Raid: %s is destroyed (grey Attack)", name)
                done.add(name)
            else:
                log.info("Raid: %s did not open its bar", name)
        if all(n in done for n in ORDER if n != "Capital Peak") and "Capital Peak" in done:
            break
    _save(bot)
    log.info("Raid: no district can be attacked now (destroyed or locked: %s)", ", ".join(sorted(done)) or "-")
    return None

# ----------------------------------------------------------------------------- the battle
def _not_allowed(frame):
    """The game's notice "Only members who were in the clan before the Raid Weekend began can attack!"."""
    x, y, w, h = space.region(*NOTICE)
    p = cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(int)
    if float((((p[:, 0] < 8) | (p[:, 0] > 172)) & (p[:, 1] > 170) & (p[:, 2] > 170)).mean()) < 0.02:
        return False
    text = re.sub(r"[^a-z]", "", " ".join(t for t, _, _ in vision.text_reader.read(frame, (x, y, w, h))).lower())
    return "before" in text and "raid" in text or "onlymembers" in text


def _wait_battle(bot, timeout):
    """Wait for the raid battle; returns "battle", "not_allowed" or None."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        f = bot.shot()
        if vision.find(f, "raid/battle_starts") or vision.find(f, "battle/surrender"):
            return "battle"
        if _not_allowed(f):
            return "not_allowed"
        control.sleep(0.3)
    return None


def start_attack(bot):
    """The district's bar is open: Attack (-> "Attack Now?" Attack) until the battle has started.
    Returns "started", "not_allowed" or "failed"."""
    x0, y0, w0, h0 = space.region(*BAR_ATTACK)
    key = None
    for _ in range(3):                               # a tap while the bar slides in is lost: again
        bot.tap(x0 + w0 // 2, y0 + h0 // 2, jitter=3)
        key = _wait_any(bot, ["raid/attack_now_title", "raid/battle_starts", "battle/surrender"], 5)
        if key:
            break
    for _ in range(3):
        if key != "raid/attack_now_title":
            break
        m = _find(bot.shot(), "raid/attack_go")
        if m:
            bot.tap_match(m)
        got = _wait_battle(bot, 8)
        if got == "not_allowed":
            return "not_allowed"
        key = "raid/battle_starts" if got == "battle" else _wait_any(bot, ["raid/attack_now_title"], 1)
    if key in ("raid/battle_starts", "battle/surrender"):
        return "started"
    bot.save_error("raid-no-battle")
    return "failed"


def deploy_spots(frame, n=6, loose=False):
    """The lit deploy area of a raid battle: up to n spots, the deepest inside it first, ZONE_GAP apart. [] when
    none is seen. loose=True: wider colours, for ground other than grass under the veil."""
    lo, hi = LIT_LOOSE if loose else LIT
    lit = (cv2.inRange(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV), np.array(lo), np.array(hi)) > 0).astype(np.uint8)
    lit[space.point(0, ZONE_BAR)[1]:, :] = 0
    for box in ZONE_UI:
        x, y, w, h = space.region(*box)
        lit[max(0, y):max(0, y + h), max(0, x):max(0, x + w)] = 0
    lit = cv2.morphologyEx(lit, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))     # flowers, stones, troops
    count, labels, stats, _ = cv2.connectedComponentsWithStats(lit)
    keep = stats[:, 4] >= ZONE_MIN
    keep[0] = False
    lit = keep[labels].astype(np.uint8)
    depth = cv2.distanceTransform(lit, cv2.DIST_L2, 5)        # how far inside the lit area each pixel is
    ys, xs = np.nonzero(depth >= space.f(ZONE_DEPTH))
    gap = space.f(ZONE_GAP) ** 2
    spots = []
    for i in np.argsort(-depth[ys, xs], kind="stable"):
        p = (int(xs[i]), int(ys[i]))
        if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= gap for q in spots):
            spots.append(p)
            if len(spots) == n:
                break
    return spots


def _probes():
    """Spots around the middle of the screen, nearest first - never on the game's buttons or the card bar."""
    step, cx, cy = space.f(PROBE_STEP), space.w / 2, space.h / 2
    bar = space.point(0, ZONE_BAR)[1]
    ui = [space.region(*b) for b in ZONE_UI]
    pts = [(int(cx + i * step), int(cy + j * step)) for i in range(-5, 6) for j in range(-4, 5)]
    pts = [p for p in pts if 0 < p[0] < space.w and 0 < p[1] < bar
           and not any(x <= p[0] < x + w and y <= p[1] < y + h for x, y, w, h in ui)]
    return sorted(pts, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)[:PROBES]

def _pan(bot):
    """Zoomed out completely and moved fully down and right: the camera then stops at the same place in every
    battle, so a district's deploy area is always at the same screen spot."""
    bot.device.zoom_out(ZOOM_PRESSES)
    for _ in range(PAN_SWIPES):
        bot.swipe(space.center(*PAN[0]), space.center(*PAN[1]), 350)
        control.sleep(0.15)
    control.sleep(0.5)                               # the camera glides on a little after the last swipe


def _miner_spots(bot, learned):
    """Where the miners may go, best first: the spot learned for this district, then the lit deploy area (read
    only when needed: on grass, then on any ground), then spots around the middle of the screen."""
    tried = []
    if learned:
        tried.append(tuple(learned))
        yield tried[-1]
    frame = bot.shot()
    for loose in (False, True):
        for p in deploy_spots(frame, loose=loose):
            if p not in tried:
                tried.append(p)
                yield p
    log.info("Raid: no lit deploy area took the miners - trying spots around the middle of the screen")
    bot.save_error("raid-no-zone", frame)
    for p in _probes():
        if p not in tried:
            yield p


def _grey(frame, box):
    """A battle card that is used up is grey (~10; the pale Frost card in colour ~58)."""
    x, y, w, h = box
    return cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2HSV)[:, :, 1].mean() <= 30


def _count(frame, box):
    """The "x10" on a battle card (its picture's box), or None when it cannot be read."""
    x, y, w, h = box
    text, _ = vision.text_reader.read_line(frame, (x + w // 3 - 6, y - 38, w * 2 // 3 + 18, 30))
    n = _digits(text)
    return n if n and n <= 50 else None


def _drop(bot, key, spots, taps, reselect=False):
    """Select a battle card and tap its whole stack on the first spot that takes it. A spot took it when the card
    turns grey (all of it out); a card that is only partly out is tapped again on that spot. The card is found
    once, before it is selected: a selected card looks different. `taps` is used when its count cannot be read.
    reselect: when nothing came out on the first spot (one that always takes it - a spell inside the district), the
    card was not selected (the game may have selected it already, and a tap unselects it): tapped again, once.
    Returns the spot that took it, or None (no such card, or no spot took it)."""
    frame = bot.shot()
    card = vision.find(frame, key, threshold=CARD_FIND)
    if not card or _grey(frame, card.box):
        log.info("Raid: no %s card to deploy", key.split("_", 1)[1])
        return None
    n = _count(frame, card.box) or taps
    bot.tap_match(card, jitter=2)
    control.sleep(0.2)
    for x, y in spots:
        for _ in range(3):                           # partly out: the rest on the same spot
            control.checkpoint()
            bot.device.tap_burst(x, y, n, 0.06)
            control.sleep(0.35)
            frame = bot.shot()
            if _grey(frame, card.box):
                return x, y
            left = _count(frame, card.box)
            if left is not None and left < n:
                n = left
                continue
            if not reselect:
                break                                # nothing came out here: the next spot
            reselect = False
            bot.tap_match(card, jitter=2)
            control.sleep(0.2)
    return None


def _into(spot, length):
    """A point `length` (battlefield px) from the spot into the district (towards INTO)."""
    tx, ty = space.center(*INTO)
    dx, dy = tx - spot[0], ty - spot[1]
    d = max(1.0, (dx * dx + dy * dy) ** 0.5)
    k = min(1.0, space.f(length) / d)
    return int(spot[0] + dx * k), int(spot[1] + dy * k)


def deploy(bot, district):
    """In the raid battle: the camera to its fixed place, all the Super Miners on the district's deploy spot
    (learned the first time from the lit area, then tapped straight away), then the spells into the district next
    to it. Returns True when the miners went out (no spell is wasted when they did not)."""
    _pan(bot)
    spots = _memory(bot, "raid_spots")
    learned = spots.get(district)
    used = _drop(bot, "raid/battle_miner", _miner_spots(bot, learned), MINER_TAPS)
    if used is None:
        log.warning("Raid: the Super Miners could not be deployed on %s: no spot took them", district)
        bot.save_error("raid-deploy")
        if learned:
            spots.pop(district, None)                # a spot that no longer works is found again next time
            _save(bot)
        return False
    if learned is None or tuple(learned) != used:
        log.info("Raid: deploy spot of %s %s: %d, %d", district, "learned" if learned is None else "moved", *used)
        spots[district] = list(used)
        _save(bot)
    for key, taps in BATTLE_CARDS:
        if _drop(bot, key, [_into(used, SPELL_IN), used], taps, reselect=True) is None:
            log.info("Raid: %s not deployed", key.split("_", 1)[1])
    return True

def restart(bot):
    """Close the game and open it again (after deploying, and to get out of a screen the bot does not know);
    the village is on screen afterwards."""
    bot.action = "Restarting the game"
    bot.device.close_game()
    end = time.monotonic() + 20
    while bot.device.is_game_running() and time.monotonic() < end:
        control.sleep(0.3)
    states.ensure_game(bot)


def leave(bot):
    """From the raid map or the Clan Capital back to the village: Map -> the Capital -> Return Home (else
    restart)."""
    for _ in range(2):
        key = _wait_any(bot, ["raid/return_home", "raid/map_button"], 8, dismiss=True)
        if not key:
            break
        bot.tap_template(key, timeout=2, after=2.0)
        if key == "raid/return_home":
            break
    if not go_home(bot, 30):
        restart(bot)


# ----------------------------------------------------------------------------- one account
def run(bot, account, max_attacks=6):
    """Use this account's raid attacks. Each starts in the village (the airship -> the raid map) and ends with
    the game closed and opened again once everything is deployed. Returns the number made."""
    name = account["name"]
    progress = bot.progress.setdefault(name, {})
    if not window()[0] or not pending(bot, name):
        return 0
    week = _weekend(bot)
    made, failed, army_set = 0, 0, False
    try:
        while made < max_attacks:
            control.checkpoint()
            bot.action = "Raid: finding the airship"
            tap, _ = find_airship(bot, name)
            if tap is None:
                break                                 # (not marked done: looked at again next run)
            screen = open_capital(bot, tap)
            if screen == "raid/next_raid":               # the summary of the last raid: Next Raid
                bot.tap_template("raid/next_raid", timeout=3)
                screen = _wait_any(bot, ["raid/attacking_title", "raid/capital_title"], 15, dismiss=True)
            if screen is None:
                fails = week.setdefault("fails", {})
                fails[name] = fails.get(name, 0) + 1
                log.info("%s: the Clan Capital did not open (%d time(s) this weekend)%s", name, fails[name],
                         " - skipped for the rest of this Raid Weekend" if fails[name] >= 3 else "")
                bot.save_error("raid-no-capital")
                if fails[name] >= 3:
                    week["done"][name] = True             # not tried again and again this weekend
                if not go_home(bot, 30):
                    restart(bot)
                break
            left = attacks_left(bot.shot())
            if left == 0:
                log.info("%s: no raid attack left this Raid Weekend", name)
                week["done"][name] = True
                leave(bot)
                break
            progress["left"] = left
            if not army_set:
                bot.action = "Raid: setting the army"
                log.info("%s: %s raid attack(s) left - army: Super Miners, 1 Frost, 2 Graveyard", name,
                         left if left is not None else "some")
                if not set_army(bot):
                    log.warning("%s: the capital army was not changed - attacking with the army it has", name)
                army_set = True
            if screen != "raid/attacking_title" and not open_raid_map(bot):
                log.info("%s: the raid map did not open", name)
                bot.save_error("raid-no-map")
                leave(bot)
                break
            bot.action = f"Raid attack {made + 1}: choosing a district"
            district = choose_district(bot)
            if district is None and bot.tap_template("raid/next_raid", timeout=2):
                _wait_any(bot, ["raid/attacking_title"], 15, dismiss=True)   # this raid is over: the next clan
                week["next"] = ORDER[0]
                district = choose_district(bot)
            if district is None:
                log.info("%s: no district can be attacked now", name)
                bot.save_error("raid-no-district")
                leave(bot)
                break
            bot.action = f"Raid attack {made + 1}: {district}"
            status = start_attack(bot)
            if status == "not_allowed":
                log.info("%s: joined the clan after this Raid Weekend began - it can raid only when promoted "
                         "(Elder); skipped this weekend", name)
                week["done"][name] = True
                leave(bot)
                break
            if status == "failed":
                failed += 1
                log.info("%s: the raid attack on %s did not start", name, district)
                _close_bar(bot)
                leave(bot)
                if failed >= 2:
                    break
                continue
            bot.action = f"Raid attack {made + 1}: deploying on {district}"
            out = deploy(bot, district)
            made += 1                                    # the attack is used once its battle has begun
            progress["raids"] = progress.get("raids", 0) + 1
            bot.stats["raids"] = bot.stats.get("raids", 0) + 1
            log.info("%s: raid attack %d on %s - %s, closing and reopening the game", name, made, district,
                     "army out" if out else "the miners did not go out")
            control.sleep(CLOSE_AFTER)
            restart(bot)
    except BotError as e:
        log.warning("%s: raid: %s", name, e)
        bot.save_error("raid-error")
        restart(bot)
    finally:
        _save(bot)
    if made:
        log.info("%s: %d raid attack(s) made", name, made)
    return made
