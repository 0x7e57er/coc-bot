"""Switch accounts through the profile menu -> Settings -> Supercell ID, by reading the account names.

One 0.5 s drag moves the Supercell ID list exactly 4 accounts, so the bot drags straight to the
account's page (keep config/accounts.json in the game's list order), reads the names there and taps
the right one.
"""

import difflib
import logging
import re
import time

import numpy as np

from . import config, vision
from .context import BotError
from .space import space
from .states import go_home

log = logging.getLogger("bot")


def normalise(name):
    """Lower-case, no spaces/punctuation; 'o'/'l'/'i' next to a digit become '0'/'1' (OCR mix-ups)."""
    s = re.sub(r"[^0-9a-z]", "", name.lower())
    s = re.sub(r"^0(?=[a-z])", "o", s)              # a leading 'O' read as zero
    for _ in range(2):
        s = re.sub(r"(?<=\d)o|o(?=\d)", "0", s)
        s = re.sub(r"(?<=\d)[il]|[il](?=\d)", "1", s)
    return s


def same_name(a, b):
    """True if two account names match. Numbers must be identical (Buggu1 != Buggu01 != Buggu10);
    the letters may differ a little (OCR reading 'Buaau20' still matches 'Buggu20')."""
    a, b = normalise(a), normalise(b)
    if a == b:
        return True
    if re.findall(r"\d+", a) != re.findall(r"\d+", b):
        return False
    la, lb = re.sub(r"\d", "", a), re.sub(r"\d", "", b)
    return difflib.SequenceMatcher(None, la, lb).ratio() >= 0.6


NOT_ACCOUNTS = ("login", "supercellid", "switchid", "otherids")

# BlueStacks draws the Supercell ID panel as an Android view of its own size (not the game's 1.2x): the
# name column is placed from the panel's "SWITCH ID" label - right of the account pictures, left of the gear
SID_COLUMN = (-136, 96, 286)       # x and y from the label's centre, width (game-space px)


def _name_column(bot, frame):
    """The column of account names in the Supercell ID panel."""
    dx, dy, w = (space.s(v) for v in SID_COLUMN)
    m = vision.find(frame, "sid/switch_id_label")
    if m:
        bot.sid_column = (m.x + dx, w)
        top = m.y + dy
    else:
        top = space.s(10)                           # the label scrolled away with the list
    x, w = getattr(bot, "sid_column", None) or (space.w - space.s(378), w)
    return x, top, w, space.h - top


def _tap_button(bot, key, point):
    """Tap a button where its picture is on this screen; its fixed spot only when it is not found."""
    m = bot.find(key)
    if m:
        bot.tap_match(m)
    else:
        bot.tap_point(point)


def _name_lines(frame, region):
    """Rows of near-black text in the name column = account names (clan/TH lines are grey)."""
    x, y, w, h = region
    dark = frame[y:y + h, x:x + w].max(axis=2) < 90
    rows = dark.sum(axis=1)
    lines, r = [], 0
    while r < len(rows):
        if rows[r] >= 3:
            start = r
            while r < len(rows) and rows[r] >= 1:
                r += 1
            if r - start >= 12:
                cols = np.where(dark[start:r].any(axis=0))[0]
                width = cols.max() - cols.min()
                if width > 45:                      # skip the small clan badge
                    lines.append((x + cols.min() - 6, y + start - 6, width + 12, r - start + 12))
        r += 1
    return lines


def read_switcher(bot, frame=None):
    """Visible accounts in the panel: [(name, (x, y) to tap, name_box)]."""
    frame = bot.shot() if frame is None else frame
    out = []
    for box in _name_lines(frame, _name_column(bot, frame)):
        text, conf = vision.text_reader.read_line(frame, box)
        if text and conf > 0.5 and not any(w in normalise(text) for w in NOT_ACCOUNTS):
            out.append((text, (box[0] + box[2] // 2, box[1] + box[3] // 2), box))
    return out


def read_town_hall(frame, name_box):
    """'Town Hall: 17' is a couple of lines below the name (how far depends on the screen):
    read the lines under the name and take the one that says Town Hall."""
    x, y, w, h = name_box
    top = y + h
    bottom = min(frame.shape[0], y + h * 5)
    if bottom - top < h:
        return 0                                   # card cut off at the bottom of the panel
    width = max(w, space.s(260))
    gray = frame[top:bottom, x:x + width].min(axis=2)
    ink = (gray < 200).sum(axis=1) >= 3               # rows with text (the card is light)
    r = 0
    while r < len(ink):                               # each text line below the name, top to bottom
        if ink[r]:
            start = r
            while r < len(ink) and ink[r]:
                r += 1
            if r - start >= 8:
                text, conf = vision.text_reader.read_line(frame, (x, top + start - 4, width, r - start + 8))
                m = re.search(r"hall\W*(\d{1,2})\s*$", text.lower())
                if m and conf > 0.5:
                    return int(m.group(1))
        r += 1
    return 0


def open_switcher(bot):
    if not go_home(bot):
        raise BotError("Not on the home village")
    for _ in range(2):                            # a tap during an animation can be lost: tap again
        # Settings is a tab of the profile menu (the profile picture, top left); the menu opens on the
        # tab used last
        bot.tap_point("home.settings")
        if bot.wait_any(["settings/title", "settings/close"], 4, interval=0.15)[0]:
            if bot.exists("settings/title") or (_tap_button(bot, "settings/tab", "profile.settings_tab") or
                                                bot.wait("settings/title", 3, interval=0.15)):
                break
        if not go_home(bot, 10):
            raise BotError("Not on the home village")
    else:
        raise BotError("Settings did not open")
    _tap_button(bot, "settings/switch_id", "settings.switch_id")    # the blue arrows next to Open
    if not bot.wait("sid/switch_id_label", 10, interval=0.15):
        raise BotError("Supercell ID panel did not open")
    # the list slides in: wait until the name column stops moving (max 1.2 s)
    prev = None
    for _ in range(12):
        f = bot.shot()
        x, y, w, h = _name_column(bot, f)
        cur = f[y:y + h, x:x + w].astype("int16")
        if prev is not None and abs(cur - prev).mean() < 1.0:
            break
        prev = cur
        bot.sleep(0.1)


ROWS_PER_PAGE = 4       # one page drag moves the list exactly 4 accounts (measured; same as completeid)


def _page(bot, down=True):
    """One page of the account list, scrolled the way completeid/XpIncrease do it: a 0.5 s drag
    released while still moving. The list moves exactly 4 accounts and is still right away."""
    if down:
        bot.drag(bot.layout.point("sid.page_from"), bot.layout.point("sid.page_to"), 500)
    else:
        bot.drag(bot.layout.point("sid.page_up_from"), bot.layout.point("sid.page_up_to"), 500)


def _scroll(bot, down=True):
    _page(bot, down)
    bot.sleep(0.25)


def _list_index(bot, name):
    """Where the account is in config/accounts.json (keep it in the game's list order)."""
    for i, a in enumerate(bot.accounts):
        if same_name(a["name"], name):
            return i
    return None


def read_player(bot, frame=None):
    """The in-game player name at the top left of the village ("" if unreadable)."""
    frame = bot.shot() if frame is None else frame
    text, conf = vision.text_reader.read_line(frame, bot.layout.region("home.player_name"))
    return text.strip() if text and conf > 0.6 else ""


def on_account(bot, account, check_name=False):
    """True if the bot switched to this account in this run (and, with check_name - after the game
    reloaded - its in-game name still matches). In-game names are not unique (several accounts can
    be called the same), so they never identify an account on their own."""
    if bot.current_account != account["name"]:
        return False
    if check_name and account.get("_player"):
        seen = read_player(bot)
        if not seen:
            bot.sleep(0.6)                            # the name appears a moment after the village
            seen = read_player(bot)
        if seen:
            return same_name(seen, account["_player"])
    return True


def switch_to(bot, account):
    """Switch to `account` (dict with "name"). Returns True."""
    name = account["name"]
    if go_home(bot, 30) and on_account(bot, account):
        log.info("Already on %s", name)
        bot.current_account, bot.current_acc = name, account
        return True
    log.info("Switching to %s", name)
    bot.action = f"Switching to {name}"
    started = time.monotonic()
    for k in [k for k in account if k.startswith("_")]:
        account.pop(k)                                # per-visit flags (army checked, ...)
    open_switcher(bot)
    state = bot.state
    # each screen scrolls the list its own amount per drag: the pages are remembered per screen size
    native = space.native or (1920, 1080)
    pages = state.setdefault(f"switcher_at_{native[0]}x{native[1]}", {})

    def try_page():
        frame = bot.shot()
        visible = read_switcher(bot, frame)
        exact = [v for v in visible if normalise(v[0]) == normalise(name)]
        for text, pt, box in exact or visible:
            if same_name(text, name):
                if not account.get("th"):             # not in accounts.json: read it from the list
                    account["th"] = read_town_hall(frame, box)
                bot.tap(*pt, jitter=4)
                return True, visible
        return False, visible

    # 1) straight to its page: learned on an earlier visit, else from its place in accounts.json
    index = _list_index(bot, name)
    ratios = sorted(_list_index(bot, n) / p for n, p in pages.items() if p and _list_index(bot, n) is not None)
    per_page = ratios[len(ratios) // 2] if ratios else ROWS_PER_PAGE
    target = pages.get(name, int(index // per_page) if index is not None else 0)
    if index is not None and abs(target - index / per_page) > 1.5:
        target = int(index // per_page)               # a page learned with an older scroll: from the list
    for _ in range(target):
        _page(bot)                                    # the list stops at once: no wait in between
    if target:
        bot.sleep(0.25)
    found, visible = try_page()
    scrolled, went_up = target, False

    # 2) not there (list changed): search towards it, then the whole list
    if not found:
        seen = [i for i in (_list_index(bot, t) for t, _, _ in visible) if i is not None]
        first = (index is None or not seen or index > max(seen))
        for down in ((True, False) if first else (False, True)):
            last = None
            for _ in range(40):
                sig = tuple(t for t, _, _ in visible)
                if sig == last:
                    break                      # list stopped moving: reached the end
                last = sig
                _scroll(bot, down=down)
                scrolled += 1 if down else 0
                went_up = went_up or not down
                found, visible = try_page()
                if found:
                    break
            if found:
                break
    if not found:
        pages.pop(name, None)                         # look for it from its place in the list next time
        config.save_state(state)
        bot.save_error("account-not-found")
        go_home(bot)
        raise BotError(f"Account '{name}' not found in the Supercell ID list")

    if went_up:
        pages.pop(name, None)                         # up-drags are shorter: guess from the list next time
    else:
        pages[name] = scrolled                        # page drags from the top to reach it
    config.save_state(state)
    if not go_home(bot, timeout=90):
        raise BotError(f"'{name}' did not finish loading")
    player = read_player(bot)
    bot.current_account, bot.current_acc = name, account
    if player:
        account["_player"] = player                   # in-game name: checked after the game reloads
    log.info("Now on %s (Town Hall %s) in %.0f s", name, account.get("th") or "?", time.monotonic() - started)
    return True
