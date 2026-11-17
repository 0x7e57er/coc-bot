"""Loot + donate: the main account donates to the requests of your other accounts, paying with elixir.

The cycle (settings "donate"), always starting on the main account (account #1, not "start from"):
  1. The main account has the elixir a round of donations needs ("need", 40 lakh)? Then the requesting accounts -
     the partner (#2) first, then the others of the top "request_top" accounts of the list (30: the main account
     and the 29 below it) - each empty their Clan Castle and request; then the main account donates to all of
     them. Its elixir is read again: enough -> again.
  2. Not enough: the main account loots until its storages are full, then the partner loots until full too (the
     partner always loots with the main one), and the requests start again with the partner.
It goes on until it is stopped.

Screens (the PC pictures, like Coc-Bot's; BlueStacks draws some screens smaller, so places inside the chat and
the donate window are measured from a button / title there and scaled like it):
  Army screen   - the Clan Castle part: a trash button (army/cc_remove) and the green Request button
                  (army/request_button), or its cooldown timer (army/request_cooldown). Removing asks
                  "Remove troops?" -> Okay.
  Request       - "Request Reinforcements" (request/title) with Send.
  Clan chat     - opened with the chat button on the left; each open request has a green Donate button.
  Donate window - "Donation Resource" (donate/window_title) with troop / spell icons; a usable one is in colour.
                  Units are paid with elixir - or GEMS when the window's resource switch is on gems: then nothing
                  is donated.
"""

import logging
import re
import time

import cv2
import numpy as np

from . import account as account_actions
from . import army, config, loot, vision
from .context import BotError
from .control import control
from .states import go_home

log = logging.getLogger("bot")


# ----------------------------------------------------------------------------- requesting (army screen)
def _active(frame, key, region=None):
    """A button in colour (enabled), not greyed out."""
    m = vision.find(frame, key, any_brightness=True, region=region)
    if not m:
        return None
    x, y, w, h = m.box
    sat = cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2HSV)[:, :, 1].mean()
    want = cv2.cvtColor(vision.templates.image(key), cv2.COLOR_BGR2HSV)[:, :, 1].mean()
    return m if sat >= want * 0.6 else None


def empty_castle(bot):
    """Empty the Clan Castle (the army screen is open). Returns True when troops were removed."""
    frame = bot.shot()
    m = vision.find(frame, "army/cc_remove", any_brightness=True)
    if not m:
        log.debug("Clan Castle remove button not found")
        return False
    x, y, w, h = m.box
    if frame[y:y + h, x:x + w].mean() < vision.templates.image("army/cc_remove").mean() * 0.75:
        log.debug("Clan Castle already empty")       # a grey trash: nothing in it (or a request is open)
        return False
    bot.tap_match(m)
    if not bot.wait("army/remove_title", 4, interval=0.2):
        log.info("Clan Castle troops are locked (a request is still open)")
        return False
    bot.tap_template("battle/confirm_okay", timeout=3, after=0.4)
    log.info("Clan Castle emptied")
    return True


WAIT_COOLDOWN = 60      # a request cooldown this close to its end is waited out


def _timer(bot, tries=4):
    """Seconds until this account can request again, from the Request button's timer ("10m", "9m 58s", "45s");
    None when it cannot be read."""
    for _ in range(tries):
        bot.sleep(0.5)
        f = bot.shot()
        m = vision.find(f, "army/request_cooldown", any_brightness=True)
        if not m:
            continue
        x, y, w, h = m.box                           # "10m" sits at the button's lower right
        text, _ = vision.text_reader.read_line(f, (x + int(w * 0.23), y + int(h * 0.55), int(w * 0.77), h // 2))
        t = text.lower().replace(" ", "").replace("o", "0").replace("l", "1").replace("i", "1")
        m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", t)
        if m and any(m.groups()):
            h, mi, se = (int(g or 0) for g in m.groups())
            return h * 3600 + mi * 60 + se
    return None


def request(bot):
    """Send a reinforcement request (the army screen is open). Returns the cooldown it started (seconds, 0 when
    it could not be read), or None when no request was sent."""
    frame = bot.shot()
    if vision.find(frame, "army/request_cooldown", any_brightness=True):
        secs = _timer(bot, tries=2)
        if not secs or secs > WAIT_COOLDOWN:
            log.info("Request is on cooldown%s (never paying gems to skip it)",
                     f" for {secs // 60}m {secs % 60}s" if secs else "")
            return None
        log.info("Request cooldown ends in %ds: waiting for it", secs)
        bot.sleep(secs + 1.5)
        frame = bot.shot()
    m = _active(frame, "army/request_button")
    if not m or m.score < 0.88:
        log.info("Request button not available (cooldown, a request still open, or the Clan Castle full)")
        return None
    bot.tap_match(m)
    if not bot.wait("request/title", 5, interval=0.2):
        log.info("The request window did not open")
        return None
    if not bot.tap_template("request/send", timeout=4, after=0.5):
        return None
    secs = _timer(bot)
    log.info("Reinforcements requested%s", f" (next request in {secs // 60}m {secs % 60}s)" if secs else "")
    return secs or 0


def in_clan(bot):
    """True / False from the chat or the "Social" button on the village; None when it cannot be told."""
    for _ in range(4):
        if not go_home(bot):
            raise BotError("Not on the home village")
        bot.sleep(0.4)
        f = bot.shot()
        if vision.find(f, "home/social_button"):
            return False
        if vision.find(f, "home/chat_button"):
            return True
        bot.sleep(1.0)                               # a dialog or an animation covers the buttons
    log.warning("Could not tell whether this account is in a clan")
    return None


def request_turn(bot, account):
    """On a requesting account: empty the Clan Castle (setting "empty_cc") and request. Returns the cooldown
    (seconds, 0 = unread), or None when it did not request."""
    if in_clan(bot) is False:
        log.warning("%s is not in a clan: it cannot request", account["name"])
        account["_no_clan"] = True
        return None
    army.open_army(bot)
    try:
        if bot.settings["donate"].get("empty_cc", True):
            empty_castle(bot)
            bot.sleep(0.4)
        return request(bot)
    finally:
        army.close_army(bot)
        go_home(bot)


# ----------------------------------------------------------------------------- donating (clan chat)
def open_chat(bot):
    if not go_home(bot):
        raise BotError("Not on the home village")
    m = bot.find("home/chat_button")
    bot.tap_match(m) if m else bot.tap_point("home.chat")
    bot.sleep(0.7)
    if bot.exists("chat/rules_understand"):         # the first time on this account
        bot.tap_template("chat/rules_understand", timeout=2, after=0.8)
    if not bot.wait_any(["chat/close", "chat/challenge"], 6)[0]:
        raise BotError("Clan chat did not open")
    m = bot.wait("chat/jump_latest", 1.5, interval=0.3)   # it stays where it was scrolled: to the newest (the
    if m:                                                   # button shows a moment after the chat)
        bot.tap_match(m)
        bot.sleep(0.7)


def close_chat(bot):
    m = bot.find("chat/close")
    bot.tap_match(m) if m else bot.tap_point("chat.close")
    bot.sleep(0.6)


def donate_buttons(frame):
    """Every Donate button in the chat (the panel on the left, 40 % of the screen), the newest request first."""
    ms = vision.find_all(frame, "chat/donate_button", region=(0, 0, frame.shape[1] * 2 // 5, frame.shape[0]))
    return sorted(ms, key=lambda m: -m.y)


def _scale(m, key):
    """How big a match is drawn relative to its picture (BlueStacks draws some screens smaller)."""
    return m.box[2] / vision.templates.image(key).shape[1]


def _box(button, dx, dy, w, h):
    """A box placed from a Donate button's centre (measured on the PC picture), scaled like the button."""
    k = _scale(button, "chat/donate_button")
    return max(0, int(button.x + dx * k)), int(button.y + dy * k), int(w * k), int(h * k)


def _fraction(frame, box):
    """ "35/50" -> (35, 50), or None."""
    text, _ = vision.text_reader.read_line(frame, box)
    m = re.search(r"(\d+)/(\d+)", text.replace(" ", "").replace("O", "0").replace("o", "0"))
    return (int(m.group(1)), int(m.group(2))) if m else None


# A custom request (the requester picked the troops) has a "Requested:" row of icons above its Donate button,
# so its name sits about 175 px higher than on a plain request.
CUSTOM_LABEL = (-420, -190, 220, 36)


def read_request(frame, button):
    """What a request card says: {"name", "troop": (have, max), "spell": ..., "siege": ...} (None = unread)."""
    label, _ = vision.text_reader.read_line(frame, _box(button, *CUSTOM_LABEL))
    custom = "request" in label.lower()
    name, _ = vision.text_reader.read_line(frame, _box(button, -420, -329 if custom else -152, 380, 38))
    return {"name": name.strip(),
            "troop": _fraction(frame, _box(button, -374, -16, 84, 32)),
            "spell": _fraction(frame, _box(button, -236, -16, 64, 32)),
            "siege": _fraction(frame, _box(button, -140, -16, 56, 32))}


def _room(req):
    """{category: space left} - None where the card could not be read (the game then decides)."""
    out = {}
    for cat in ("troop", "spell", "siege"):
        f = req.get(cat)
        out[cat] = max(0, f[1] - f[0]) if f else None
    return out


def _items(settings):
    out = []
    for i in settings["donate"].get("items", []):
        if i.get("enabled", True) and i.get("template") and vision.templates.has(i["template"]):
            out.append(dict(i, category=i.get("category") or "troop", space=max(1, int(i.get("space") or 1))))
    return out


def plan(req, items):
    """The items that fit this request, siege machines last (reaching them slides the troop rows away).
    Returns (items, room left)."""
    room = _room(req)
    usable = [i for i in items if room.get(i["category"]) != 0]
    return [i for i in usable if i["category"] != "siege"] + [i for i in usable if i["category"] == "siege"], room


# The donate window is drawn next to its request, so it moves up for requests higher in the chat. Its parts are
# measured on the PC picture with the window at its lowest place (title at BASE_TITLE).
BASE_TITLE = (662, 268)
ROWS = {"troop": (630, 375, 840, 320), "siege": (630, 375, 840, 320), "spell": (630, 720, 840, 180)}


def _window(frame):
    """The open donate window: (x, y, scale) of its title; None when it is closed."""
    m = vision.find(frame, "donate/window_title")
    return None if m is None else (m.box[0], m.box[1], _scale(m, "donate/window_title"))


def _part(region, win):
    """A part of the donate window, placed from where its title is now and scaled like it."""
    tx, ty = BASE_TITLE
    ax, ay, k = win
    x, y, w, h = region
    return max(0, int(ax + (x - tx) * k)), max(0, int(ay + (y - ty) * k)), int(w * k), int(h * k)


def gem_prices(frame, win):
    """True when the donate window charges GEMS (its "Donation Resource" switch is on gems: the prices on the
    troops are green). Then nothing is donated - ever."""
    x, y, w, h = _part((640, 490, 820, 30), win)
    patch = frame[y:y + h, x:x + w]
    if patch.size == 0:
        return False
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(int)
    hue, sat, val = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    gem = int(((hue >= 40) & (hue <= 90) & (sat > 120) & (val > 120)).sum())
    pink = int(((hue >= 135) & (hue <= 170) & (sat > 90) & (val > 90)).sum())
    return gem > 150 and gem > pink                  # (elixir prices: under 50 green, hundreds pink)


def is_big(frame, win, settings):
    """A big request (lots of room): the Super Wizard (10 housing space) is only in colour then - the big items
    go to it, the small ones to the others."""
    key = settings["donate"].get("big_template", "donate/super_wizard")
    return bool(key and vision.templates.has(key) and _active(frame, key, _part(ROWS["troop"], win)))


def _settled(bot, region, timeout=2.0):
    """After a flick the row bounces at its end: the frame once it stands still (a tap on a moving row only
    stops it)."""
    x, y, w, h = region
    bot.sleep(0.5)
    last = bot.shot()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        bot.sleep(0.2)
        f = bot.shot()
        if np.abs(f[y:y + h, x:x + w].astype(np.int16) - last[y:y + h, x:x + w]).mean() < 1.5:
            return f
        last = f
    return last


def _tile(bot, frame, key, win, cat):
    """An item's icon in the donate window, in colour. Siege machines are at the far right end of the troop rows:
    the row is flicked to its end in one fast move. Returns (match or None, frame)."""
    region = _part(ROWS[cat], win)
    m = _active(frame, key, region)
    if m or cat != "siege":
        return m, frame
    x, y, w, h = region
    cy = y + h // 3
    still = 0
    frame = _settled(bot, region)                    # the window updates for a moment after the last taps
    for _ in range(4):
        if vision.find(frame, key, region=region, any_brightness=True, threshold=0.8):
            return None, frame                       # there but grey: not for this request
        before = frame[y:y + h, x:x + w].astype(np.int16)
        bot.drag((x + w * 3 // 4, cy), (5, cy), 90)  # released while moving: the row flies to its end
        frame = _settled(bot, region)
        m = _active(frame, key, region)
        if m:
            return m, frame
        if np.abs(frame[y:y + h, x:x + w].astype(np.int16) - before).mean() < 2:
            still += 1
            if still == 2:
                break                                # the row did not move twice: its end is reached
    return None, frame


def fill(bot, items, big, room):
    """The donate window is open: each item in one quick burst of taps. With the request's room known, exactly
    the taps that fit are made (35 troop space = 7 Balloons, 2 free siege slots = 2 machines), else the item's
    "clicks"; items marked "big" go only to big requests, "small" only to the others (a free siege slot always gets
    its machine). Returns the units donated."""
    taps = 0
    room = dict(room)
    frame = bot.shot()
    for item in items:
        use, cat = item.get("use", "all"), item["category"]
        if cat != "siege" and ((use == "big" and not big) or (use == "small" and big)):
            continue
        win = _window(frame)
        if win is None:
            break                                    # the request is full: the window closed itself
        free = room.get(cat)
        n = free // item["space"] if free is not None else max(1, int(item.get("clicks", 1)))
        if n <= 0:
            continue
        m, frame = _tile(bot, frame, item["template"], win, cat)
        if not m:
            log.debug("donate %s: not available (grey or not found)", item.get("name"))
            continue
        log.debug("donate %s: %d tap(s)", item.get("name"), n)
        bot.tap_burst(m, n, 0.25 if cat == "siege" else 0.05)
        taps += n
        if free is not None:
            room[cat] = free - n * item["space"]
        control.sleep(0.15)
        frame = bot.shot()
    return taps


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _is_mine(bot, name):
    """A request from one of your accounts: its name is an account's name or its in-game name (read when the bot
    opened it)."""
    same = account_actions.same_name
    return any(same(a["name"], name) or (a.get("_player") and same(a["_player"], name)) for a in bot.accounts)


def donate_all(bot, max_requests=60):
    """The main account: donate to every open request in the clan chat (setting "only_mine": only to your own
    accounts), scrolling up to older messages until no new Donate button shows. Returns (units, requests)."""
    items = _items(bot.settings)
    if not items:
        raise BotError("Nothing to donate: settings donate.items has no item with a picture")
    only_mine = bot.settings["donate"].get("only_mine", False)
    open_chat(bot)
    total, handled = 0, 0
    page, empty_pages = 0, 0
    tried, done, visits, skipped = set(), set(), {}, set()
    saved_zero = False
    try:
        while handled < max_requests and empty_pages < 3:
            control.checkpoint()
            frame = bot.shot()
            buttons = [b for b in donate_buttons(frame) if (page, b.y // 12) not in tried]
            if not buttons:
                empty_pages += 1
                page += 1
                bot.swipe(bot.layout.point("chat.scroll_from"), bot.layout.point("chat.scroll_to"), 500)
                bot.sleep(0.8)
                continue
            empty_pages = 0
            b = buttons[0]
            tried.add((page, b.y // 12))
            req = read_request(frame, b)
            who = req["name"] or "?"
            # several accounts can share an in-game name: a request is its name + its room, so each is donated to
            ident = "|".join([_norm(req["name"]) or f"?{page}:{b.y}"]
                             + [str(req[c]) for c in ("troop", "spell", "siege")])
            if ident in done or visits.get(ident, 0) >= 3:
                continue
            if only_mine and req["name"] and not _is_mine(bot, req["name"]):
                if req["name"] not in skipped:
                    log.info("Skipping %s's request (not one of your accounts)", who)
                    skipped.add(req["name"])
                continue
            order, room = plan(req, items)
            log.info("Request from %s - room left: troops %s, spells %s, siege %s", who,
                     *(("?" if room[c] is None else room[c]) for c in ("troop", "spell", "siege")))
            if not order:
                log.info("Nothing to give %s: the request is full or nothing fits", who)
                done.add(ident)
                continue
            now = [m for m in donate_buttons(bot.shot()) if abs(m.y - b.y) < 14]
            if not now:                              # the chat moved while reading (a filled request goes away)
                tried.discard((page, b.y // 12))
                bot.sleep(0.6)
                continue
            visits[ident] = visits.get(ident, 0) + 1
            bot.tap_match(now[0])
            if not bot.wait("donate/window_title", 4):
                log.info("The donate window for %s did not open", who)
                tried.discard((page, b.y // 12))
                continue
            handled += 1
            g = bot.shot()
            win = _window(g)
            if win and gem_prices(g, win):
                log.error("The donate window charges GEMS ('Donation Resource' is set to gems in the game): nothing "
                          "is donated. Set it back to elixir in the game.")
                bot.save_error("donate-gem-prices", g)
                bot.tap_point("donate.close")
                bot.sleep(0.6)
                break
            big = bool(win) and is_big(g, win, bot.settings)
            n = fill(bot, order, big, room)
            if not n and any(room.get(c) for c in ("troop", "spell", "siege")) and not saved_zero:
                saved_zero = True                    # the first request with room that got nothing: a picture
                bot.save_error("donate-nothing", g)
            if not n:
                done.add(ident)                      # nothing more fits / nothing available
            else:                                    # a filled request goes away and the chat shifts: read again
                tried = {t for t in tried if t[0] != page}
            total += n
            bot.stats["donated"] = bot.stats.get("donated", 0) + n
            log.info("Donated %d unit(s) to %s%s", n, who, " (big request)" if big else "")
            if bot.exists("donate/window_title"):
                bot.tap_point("donate.close")        # beside the window: closes it
                bot.sleep(0.6)
            bot.sleep(0.4)
    finally:
        close_chat(bot)
        go_home(bot)
    log.info("Donating done: %d unit(s) to %d request(s)", total, handled)
    return total, handled


# ----------------------------------------------------------------------------- the cycle
def _account(bot, pos):
    """Account #pos in accounts.json (1 = the first), or None."""
    pos = int(pos or 0)
    return bot.accounts[pos - 1] if 1 <= pos <= len(bot.accounts) else None


def roles(bot):
    """(main, partner, requesters): the main account donates; the partner loots with it and requests first; then
    the other accounts of the top "request_top" of the list request too (ticks do not matter here)."""
    d = bot.settings["donate"]
    main = _account(bot, d.get("main", 1))
    partner = _account(bot, d.get("partner", 2))
    if partner is main:
        partner = None
    top = int(d.get("request_top", 30) or 0) or len(bot.accounts)
    others = [a for a in bot.accounts[:top] if a is not main and a is not partner]
    return main, partner, ([partner] if partner else []) + others


def _status(bot, acc, status, **extra):
    p = bot.progress.setdefault(acc["name"], {})
    p["status"] = status
    p.update(extra)


def _switch(bot, acc):
    from .runner import with_recovery
    return with_recovery(bot, f"switch to {acc['name']}", lambda: account_actions.switch_to(bot, acc))


def main_elixir(bot, main):
    """Open the main account and read its elixir (None when it cannot be read)."""
    if not _switch(bot, main):
        raise BotError(f"Could not open the main account {main['name']}")
    bot.action = "Reading the main account's elixir"
    for _ in range(3):
        value = loot.home_resources(bot).get("elixir")
        if value is not None:
            bot.progress.setdefault(main["name"], {})["res"] = {"elixir": value}
            return value
        bot.sleep(1.0)
    return None


SWITCH_SECS = 15        # about how long switching to an account takes


def _cooldown_left(acc, state):
    """Seconds until this account can request again (<= 0: it can now)."""
    at = state.get("requested_at", {}).get(acc["name"])
    return -1.0 if at is None else at + (state.get("cooldown") or 600) - time.time()


def request_round(bot, requesters, state):
    """Each requesting account in turn empties its Clan Castle and requests. One whose request cooldown is far
    from over is passed over this round (one that ends within a minute is waited for). Returns requests sent."""
    from .runner import with_recovery
    requested_at = state.setdefault("requested_at", {})
    sent = 0
    for acc in requesters:
        control.checkpoint()
        name = acc["name"]
        left = _cooldown_left(acc, state)
        if left > WAIT_COOLDOWN + SWITCH_SECS:
            log.info("%s: request cooldown %dm %ds left - passed over this round", name, int(left) // 60,
                     int(left) % 60)
            _status(bot, acc, "cooldown")
            continue
        if acc.get("_no_clan"):
            _status(bot, acc, "no_clan")
            continue
        _status(bot, acc, "requesting")
        bot.action = f"Requesting troops on {name}"
        if not _switch(bot, acc):
            _status(bot, acc, "skipped")
            continue
        secs = with_recovery(bot, f"request on {name}", lambda a=acc: request_turn(bot, a))
        if secs is None:
            _status(bot, acc, "no_clan" if acc.get("_no_clan") else "not_requested")
            continue
        sent += 1
        requested_at[name] = time.time()
        if secs > 60:
            if abs(secs - (state.get("cooldown") or 600)) > 30:
                log.info("The clan's request cooldown is %dm %ds", secs // 60, secs % 60)
            state["cooldown"] = secs                 # the rounds follow the clan's cooldown (perks shorten it)
        bot.stats["requests"] = bot.stats.get("requests", 0) + 1
        _status(bot, acc, "requested")
        config.save_state(bot.state)
    return sent


def donate_round(bot, main):
    """Open the main account and donate to every open request. Returns the units donated."""
    from .runner import with_recovery
    _status(bot, main, "donating")
    bot.action = "Donating"
    if not _switch(bot, main):
        _status(bot, main, "skipped")
        return 0
    got = with_recovery(bot, "donate", lambda: donate_all(bot))
    units = got[0] if got else 0
    p = bot.progress.setdefault(main["name"], {})
    p["donated"] = p.get("donated", 0) + units
    _status(bot, main, "donated")
    return units


LOOT_FAILED = ("no_army", "no_gold", "skipped", "limit")
RETRY_LOOT = 300        # the main account could not loot: tried again after this many seconds


def run(bot):
    """Loot + donate until stopped (see the top of this file)."""
    from .runner import loot_account
    main, partner, requesters = roles(bot)
    if main is None:
        raise RuntimeError("Loot + donate: the main account # is not in the account list")
    need = int(bot.settings["donate"].get("need", 4_000_000) or 0)
    state = bot.state.setdefault("donate", {})
    log.info("Loot + donate: %s donates, %s loots with it; requesting: %s; a round needs %s elixir", main["name"],
             partner["name"] if partner else "no partner", ", ".join(a["name"] for a in requesters) or "nobody",
             f"{need:,}")
    if not requesters:
        raise RuntimeError("Loot + donate: no account to request troops (raise 'Request troops from the top')")
    looted, rounds = False, 0
    while True:
        control.checkpoint()
        if not looted:                               # (just looted to full: straight to the requests)
            elixir = main_elixir(bot, main)
            if elixir is None:
                log.warning("%s: the elixir could not be read - donating anyway", main["name"])
            elif elixir < need:
                log.info("%s has %s elixir, a round needs %s: looting %s%s until full", main["name"], f"{elixir:,}",
                         f"{need:,}", main["name"], f" and {partner['name']}" if partner else "")
                loot_account(bot, main)
                result = bot.progress.get(main["name"], {}).get("status")
                if result in LOOT_FAILED:
                    log.warning("%s could not loot (%s): trying again in %d min", main["name"], result,
                                RETRY_LOOT // 60)
                    bot.action = "Waiting: the main account could not loot"
                    control.sleep(RETRY_LOOT)
                    continue
                if partner:
                    loot_account(bot, partner)
                looted = True
                continue
            else:
                log.info("%s has %s elixir (a round needs %s)", main["name"], f"{elixir:,}", f"{need:,}")
        looted = False
        wait = _cooldown_left(requesters[0], state) - SWITCH_SECS
        if wait > WAIT_COOLDOWN:
            log.info("Waiting %dm %ds for %s's request cooldown", int(wait) // 60, int(wait) % 60,
                     requesters[0]["name"])
            bot.action = f"Waiting for the request cooldown ({int(wait // 60)}m {int(wait % 60)}s)"
            control.sleep(wait)
        rounds += 1
        log.info("Donation round %d: requests from %d account(s), then %s donates", rounds, len(requesters),
                 main["name"])
        sent = request_round(bot, requesters, state)
        units = donate_round(bot, main)
        log.info("Donation round %d: %d request(s) sent, %d unit(s) donated", rounds, sent, units)
        if not sent and not units:
            log.info("Nothing was requested or donated: waiting a minute before the next round")
            bot.action = "Waiting: nothing to request or donate"
            control.sleep(60)
