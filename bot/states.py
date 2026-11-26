"""Which screen is the game on, and how to get back to the home village."""

import logging
import re
import time

import cv2
import numpy as np

from . import net, vision
from .context import BotError
from .control import control
from .space import space

log = logging.getLogger("bot")

# Order matters: overlays that leave the village buttons visible (chat, "Anyone there?") come
# first, then the village itself (the most common screen: checked early to save time; every
# other overlay dims the village buttons, so they cannot match under it), then the rest.
STATES = [
    ("exit_dialog", ["popup/exit_title"]),        # "Confirm Exit - quit the game?": ALWAYS Cancel, never Okay
    ("wall_dialog", ["wall/dialog_title"]),       # "Upgrade Walls ... for 40000 Gold?" left open: Cancel
    ("maintenance", ["popup/maintenance"]),       # "Maintenance break" (news page): wait its estimated time
    ("live_replay", ["battle/live_replay"]),      # someone attacks this village right now: wait until it ends
    ("shop", ["shop/close", "shop/title"]),       # the Shop (gem / money offers): only ever its X
    ("welcome_back", ["popup/welcome_back"]),     # "Welcome Back Chief! Your Village was Attacked": its Okay
    ("reload", ["popup/try_again", "popup/reload_device", "popup/reload", "popup/anyone_there"]),
    ("donate", ["donate/window_title"]),
    ("chat", ["chat/close"]),                     # clan chat open over the village
    ("bb_home", ["bb/trophy_hammer"]),            # Builder Base village (night): before "home"
    # the Build button (not in battles) and the dark elixir drop (not in the Builder Base), both undimmed
    ("home", ["home/build_button", "home/dark_drop"]),
    ("daily", ["popup/daily_title"]),
    ("reward_popup", ["popup/hoggy_title"]),        # Hoggy Bank rewards etc.: Continue
    ("shield_info", ["popup/shield_title"]),       # Magic Shield info: Continue only, NEVER "Remove"
    ("lab_window", ["lab/in_progress_title"]),     # laboratory after starting research (has a gems button!)
    ("upgrade_window", ["upgrade/confirm", "upgrade/close", "lab/close"]),   # any big window with a red X
    ("dialog", ["popup/speech_corner"]),          # event/tutorial character talking
    ("switcher", ["sid/switch_id_label"]),
    ("settings", ["settings/title"]),
    ("army", ["army/my_army_title"]),
    ("attack_menu", ["attack_menu/find_match", "attack_menu/edit_army"]),   # (Battle card grey: no army)
    ("remove_dialog", ["army/remove_title"]),      # "Remove troops?" -> Cancel when lost
    ("request_window", ["request/title"]),         # request window -> Cancel when lost
    ("results", ["results/claim_reward", "results/return_home"]),
    ("chest", ["chest/skip_title", "chest/skip", "chest/continue", "chest/room", "chest/pedestal",
               "chest/tap_text"]),
    ("confirm", ["battle/confirm_okay"]),
    ("scout", ["scout/next"]),              # "Available Loot" stays visible in battle, Next does not
    ("battle", ["battle/surrender"]),
]

CLOSE_BUTTONS = ["settings/close", "army/close", "sid/close", "build/close"]   # build: the Build side panel
# Buttons worth tapping wherever they appear when the screen is not recognised.
ANYWHERE_BUTTONS = ["results/return_home", "results/claim_reward", "chest/skip", "chest/continue",
                    "popup/continue_green",
                    "popup/okay_blue",          # the white "Items Delivered" box (a store gift / purchase)
                    "battle/confirm_okay",
                    "popup/try_again", "popup/reload_device", "popup/reload", "popup/daily_claim",
                    "popup/close_x"]


# Dark system dialogs - the game's own and Android's (a flat dark-grey box with capital-letter buttons):
#   connection lost / network failed -> TRY AGAIN, another device opened this account -> RELOAD,
#   idle too long ("Anyone there?") -> RELOAD GAME, Google Play's "Rate Clash of Clans" -> NEVER ...
RELOAD_KEYS = ["popup/try_again", "popup/reload", "popup/reload_device"]   # RELOAD GAME before its prefix RELOAD
RELOAD_LOG = {"popup/try_again": "Connection lost: tapping Try Again",
              "popup/reload_device": "Another device opened this account: opening it here again",
              "popup/reload": "The game asks to reload (idle too long): Reload Game"}
# the buttons the bot presses on such a dialog, best first (read with the text reader). Never "Review",
# "Exit", "Update", "Buy" ... and on "Confirm Exit" only Cancel.
DIALOG_BUTTONS = [("reloadgame", "reload"), ("reload", "reload"), ("tryagain", "try_again"), ("retry", "try_again"),
                  ("never", "close"), ("later", "close"), ("notnow", "close"), ("nothanks", "close"),
                  ("cancel", "close"), ("close", "close"), ("closeapp", "close"), ("okay", "close"), ("ok", "close")]
SYSTEM_REGION = (160, 120, 1600, 840)


def dialog_box(frame):
    """A system dialog (a flat dark-grey box in the middle of the screen: (30, 28, 25) in the PC game,
    (64, 57, 54) or (66, 66, 66) on Android), if one is on screen: (x, y, w, h) or None. Cheap, so the
    (slow) text reading only runs when there really is such a dialog."""
    H, W = frame.shape[:2]
    step = 4                                         # every 4th pixel is plenty for a box this big
    mid = frame[int(H * 0.42):int(H * 0.58):step, int(W * 0.38):int(W * 0.62):step].astype(np.int16)
    q = mid // 8
    counts = np.bincount((q[:, :, 0] * 1024 + q[:, :, 1] * 32 + q[:, :, 2]).ravel(), minlength=32768)
    top = int(counts.argmax())
    if counts[top] < counts.sum() * 0.25:
        return None                                  # the middle of the screen is not one flat colour
    colour = np.array([top // 1024, (top // 32) % 32, top % 32]) * 8 + 4
    if colour.min() < 14 or colour.max() > 100 or colour.max() - colour.min() > 24:
        return None                                  # not a dark neutral grey (black = loading screen)
    x, y, w, h = space.region(*SYSTEM_REGION)
    roi = frame[y:y + h:step, x:x + w:step].astype(np.int16)
    mask = (np.abs(roi - colour).max(axis=2) <= 7).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))     # fill the text
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
    cx, cy = (W // 2 - x) // step, (H // 2 - y) // step
    best = None
    for i in range(1, n):
        l, t, bw, bh, area = stats[i]
        if l <= cx <= l + bw and t <= cy <= t + bh and (best is None or area > best[4]):
            best = stats[i]
    if best is None:
        return None
    l, t, bw, bh, area = (int(v) for v in best)
    box = (x + l * step, y + t * step, bw * step, bh * step)
    bx, by, bw, bh = box
    if not (abs(bx + bw / 2 - W / 2) < W * 0.12 and abs(by + bh / 2 - H / 2) < H * 0.2
            and 0.25 * W <= bw <= 0.75 * W and 0.12 * H <= bh <= 0.6 * H and area * step * step > 0.6 * bw * bh):
        return None                                  # not centred / not dialog-sized (e.g. clan chat)
    return box


_last_dialog_log = {}


def _log_once(key, msg, *args, level=logging.WARNING):
    now = time.monotonic()
    if now - _last_dialog_log.get(key, 0) > 60:
        _last_dialog_log[key] = now
        log.log(level, msg, *args)


def another_device(bot):
    """Someone opened this account on another device (your phone): wait the minutes the settings say before Reload,
    so you can keep playing there (0 = Reload at once)."""
    minutes = float(bot.settings.get("another_device_wait", 0) or 0)
    if minutes <= 0:
        return
    log.info("Another device is playing on %s: waiting %g min before Reload", bot.current_account or "this account",
             minutes)
    end = time.monotonic() + minutes * 60
    while time.monotonic() < end:
        left = int(end - time.monotonic())
        bot.action = f"Waiting: another device is playing ({left // 60}m {left % 60:02d}s before Reload)"
        control.sleep(min(5, max(0.1, end - time.monotonic())))
    log.info("Reloading after waiting for the other device")


def _reloading(bot, kind):
    """Before / after a Try Again or Reload: offline -> wait for the internet first (so the bot keeps
    trying instead of restarting the game again and again); then remember to check the account."""
    if kind == "try_again":
        net.wait_until_online()
    bot.reloaded = True
    bot.reload_at = time.monotonic()


def press_reload(bot, frame):
    """Tap the game's Try Again / Reload button where its picture is. Returns True if tapped."""
    for k in RELOAD_KEYS:
        m = vision.templates.has(k) and vision.find(frame, k)
        if m:
            _log_once(k, RELOAD_LOG[k])
            if k == "popup/reload_device":
                another_device(bot)
            _reloading(bot, "try_again" if k == "popup/try_again" else "reload")
            bot.tap_match(m)
            return True
    return False


def system_dialog(bot, frame, box=None):
    """A dark system dialog (the game's or Android's): read its text and press the best button (Reload,
    Try Again, Never / Later / Cancel / Okay ...). Returns what was pressed ("reload", "try_again",
    "close") or None when there is no such dialog or no button the bot may press."""
    box = box or dialog_box(frame)
    if box is None:
        return None
    x, y, w, h = box
    lines = [(t, c, b) for t, c, b in vision.text_reader.read(frame, box) if c > 0.6]
    words = lambda t: re.sub(r"[^a-z]", "", t.lower())          # noqa: E731
    title = " ".join(t for t, _, b in lines if b[1] < y + h * 0.45)
    buttons = [(words(t), t, b) for t, _, b in lines if b[1] >= y + h * 0.45]
    allowed = DIALOG_BUTTONS
    if re.search(r"exit|quit", " ".join(t for t, _, _ in lines).lower()):
        allowed = [("cancel", "close")]                           # "Confirm Exit": never Okay
    for word, kind in allowed:
        for text, label, (bx, by, bw, bh) in buttons:
            if text == word:
                _log_once("dialog:" + title + word, "Dialog '%s': pressing %s", title or "?", label.strip())
                if kind == "reload" and "anotherdevice" in words(title):
                    another_device(bot)
                if kind != "close":
                    _reloading(bot, kind)
                bot.tap(bx + bw // 2, by + bh // 2, jitter=2)
                return kind
    _log_once("dialog:" + title, "Dialog '%s' has no button the bot may press (%s)", title or "?",
              ", ".join(label for _, label, _ in buttons) or "none read")
    return None


def after_reload(bot):
    """After a reload the game shows the account it had; make sure it is still the one the bot
    was working on (it usually is), else open that one again."""
    bot.reloaded = False
    acc = getattr(bot, "current_acc", None)
    if not acc or getattr(bot, "_reopening", False):
        return
    from . import account
    if account.on_account(bot, acc, check_name=True):
        log.info("Back on %s after the reload", acc["name"])
        return
    log.warning("After the reload the game shows another account: opening %s again", acc["name"])
    bot._reopening = True
    try:
        bot.current_account = None
        account.switch_to(bot, acc)
    finally:
        bot._reopening = False


def placement(frame):
    """A building waiting to be placed (after buying one): its green tick and red X, drawn at the
    map's zoom (so at any size). Returns (tick, cross) matches, either can be None."""
    small = cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)   # half size: 4x faster
    found = {}
    for key, hues in (("building/place_ok", (35, 90)), ("building/place_cancel", (0, 12))):
        if not vision.templates.has(key):
            continue
        base = vision.templates.image(key)
        best = None
        for sc in (0.8, 0.9, 1.0, 1.1, 1.2):
            tpl = cv2.resize(base, None, fx=sc / 2, fy=sc / 2, interpolation=cv2.INTER_AREA)
            _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(small, tpl, cv2.TM_CCOEFF_NORMED))
            if score >= 0.8 and (best is None or score > best[0]):
                h, w = tpl.shape[0] * 2, tpl.shape[1] * 2
                best = (score, vision.Match(loc[0] * 2 + w // 2, loc[1] * 2 + h // 2, float(score),
                                            (loc[0] * 2, loc[1] * 2, w, h)))
        m = best[1] if best else None
        if m:
            x, y, w, h = m.box
            hsv = cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2HSV)
            px = hsv[(hsv[..., 1] > 120) & (hsv[..., 2] > 100)]
            hue = float(np.median(px[:, 0])) if len(px) > 30 else -1
            if hues[0] <= hue <= hues[1] or (key.endswith("cancel") and hue >= 165):
                found[key] = m                     # the right colour: a tick is green, a cross red
    tick, cross = found.get("building/place_ok"), found.get("building/place_cancel")
    if tick and cross and not (tick.x > cross.x and abs(tick.y - cross.y) < 25):
        return None, None                          # not the pair (the tick is right of the cross)
    return tick, cross


def cancel_placement(bot, frame=None):
    """Leave placement mode with the red X (nothing is bought). Returns True if it was open."""
    frame = bot.shot() if frame is None else frame
    _, cross = placement(frame)
    if cross:
        bot.tap_match(cross, jitter=1)
        control.sleep(1.0)
        log.info("Left placement mode (cancelled)")
        return True
    return False


def detect(frame):
    for name, keys in STATES:
        if name == "reload" and dialog_box(frame) is not None:
            return "reload"                      # the village behind those dialogs is not dimmed
        have = [k for k in keys if vision.templates.has(k)]
        if name == "home":
            # the Build button (not in battles), and the dark elixir drop - or, for an account without dark
            # elixir yet, the green + of the gems (both not in the Builder Base, which is checked before)
            if vision.find(frame, "home/build_button") and (
                    vision.find(frame, "home/dark_drop")
                    or (vision.templates.has("home/gem_plus") and vision.find(frame, "home/gem_plus"))):
                return name
            continue
        for k in have:
            if vision.find(frame, k):
                return name
    return "unknown"


def tutorial_bubble(frame):
    """A character's speech bubble (the new-UI tutorials: "Settings has moved...", "Easily view
    Battle Logs..."): the match of its top-left ornament, or None."""
    if not vision.templates.has("popup/speech_corner"):
        return None
    return vision.find(frame, "popup/speech_corner", any_brightness=True)


TUTORIAL_TAPS = [            # tutorials that wait for a button instead of a tap on the message
    (("builder", "menu"), "top.builders_menu"),        # "Let's view the new Builder Menu!" -> Build button
]


def dismiss_tutorial(bot, frame=None):
    """Close a tutorial speech bubble of the game: tap the message, or - for the ones that point at a
    button with an arrow (e.g. the new Builder Menu) - tap that button and close what it opens.
    True if there was one."""
    frame = bot.shot() if frame is None else frame
    m = tutorial_bubble(frame)
    if not m:
        return False
    x, y, w, h = m.box
    text = " ".join(t for t, _, _ in vision.text_reader.read(frame, (x, y, space.s(430), space.s(170)))).lower()
    for words, point in TUTORIAL_TAPS:
        if all(wd in text for wd in words):
            log.info("Game tutorial (%s): tapping the button it points at", " ".join(words))
            bot.tap_point(point, jitter=3)
            control.sleep(1.5)
            for _ in range(5):                         # the tutorial may go on inside: tap its messages
                b = tutorial_bubble(bot.shot())
                if not b:
                    break
                bot.tap(b.x + space.s(180), b.y + space.s(60), jitter=4)
                control.sleep(1.0)
            if vision.templates.has("build/close") and vision.find(bot.shot(), "build/close"):
                bot.tap_point("build.close")
                control.sleep(0.6)
            return True
    bot.tap(m.x + space.s(180), m.y + space.s(60), jitter=4)
    log.info("Closed a tutorial message of the game")
    control.sleep(0.8)
    return True


def _close_any_popup(bot, frame):
    """Unknown screen: tap a known button or a red X if one is anywhere, else tap empty forest."""
    full = (0, 0, frame.shape[1], frame.shape[0])
    for k in ANYWHERE_BUTTONS:
        if vision.templates.has(k):
            m = vision.find(frame, k, region=full)
            if m:
                if k in RELOAD_KEYS:
                    _log_once(k, RELOAD_LOG[k])
                    _reloading(bot, "try_again" if k == "popup/try_again" else "reload")
                bot.tap_match(m)
                return
    for k in CLOSE_BUTTONS:
        if vision.templates.has(k):
            m = vision.find(frame, k, region=full, threshold=0.8)
            if m:
                bot.tap_match(m, jitter=2)
                return
    if cancel_placement(bot, frame):
        return
    _tap_empty(bot, frame)


def _tap_empty(bot, frame):
    """Tap an empty spot of whichever village is behind the popup (each has its own)."""
    bb = vision.templates.has("bb/trophy_hammer") and vision.find(frame, "bb/trophy_hammer", any_brightness=True)
    bot.tap_point("bb.safe" if bb else "home.safe", jitter=5)


SURRENDER_WIDE = (0, 560, 560, 520)      # bottom-left quarter: where the Surrender button can be


def surrender(bot, frame=None, blind=False):
    """End a battle in progress: Surrender, then Okay. The button is looked for where it usually is,
    then in the whole bottom-left corner; blind=True (the caller knows a battle is running) also
    taps its usual spot when it cannot be seen. Returns True if the battle was ended."""
    frame = bot.shot() if frame is None else frame
    m = (vision.find(frame, "battle/surrender") or
         vision.find(frame, "battle/surrender", region=space.region(*SURRENDER_WIDE), threshold=0.75,
                     any_brightness=True))
    if m:
        bot.tap_match(m)
    elif blind:
        x, y, w, h = vision.templates.meta("battle/surrender")["box"]
        bot.tap(*space.point(x + w // 2, y + h // 2), jitter=2)
    else:
        return False
    return bool(bot.tap_template("battle/confirm_okay", timeout=3))


MAINTENANCE_TIME = (1650, 50, 250, 80)     # "Estimated time 39m" at the top right of the maintenance page
LIVE_REPLAY_MAX = 300                     # an attack lasts 3 minutes at most (+ its results)
_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_time(text):
    """Seconds in a game time like "2d 4h", "45m 10s", "3h" (None if it is not a time)."""
    t = re.sub(r"[^0-9a-z|]", "", (text or "").lower())
    # digits the text reader mistakes for letters: a unit always follows a number, so an "s" that does not
    # is a 5 ("SH50M" = 5h 50m); "o" is a 0, "l" / "i" / "|" a 1
    t = re.sub(r"(?<!\d)s", "5", t).translate(str.maketrans("oli|", "0111"))
    parts = re.findall(r"(\d+)([dhms])", t)
    if not parts or re.sub(r"\d+[dhms]", "", t):
        return None
    return sum(int(n) * _UNITS[u] for n, u in parts)


def wait_maintenance(bot, frame):
    """Supercell's maintenance break: nothing can be done until it is over. Wait the time it shows
    (checking every minute), then restart the game."""
    secs = None
    for text, _, _ in vision.text_reader.read(frame, space.region(*MAINTENANCE_TIME)):
        secs = parse_time(text) or secs
    secs = secs or 15 * 60
    log.warning("The game is in a maintenance break (about %d min): waiting, then going on", secs // 60 + 1)
    until = time.monotonic() + secs + 60
    while time.monotonic() < until:
        control.sleep(60)
        if not vision.find(bot.shot(), "popup/maintenance"):
            break                                     # over (or the game shows something else now)
    restart_game(bot)


RUNNING_CHECK = 10          # an unknown screen this long: is the game still running? (ADB)
STUCK_RESTART = 60          # an unknown screen (or a dialog without a known button) this long: restart the game
CHEST_TAPS = 80             # a chest opening this many rewards is still progress (the time limit grows with it)


def _restart_now(bot, why):
    """Close Clash of Clans with ADB and start it again (inside go_home, which then waits for the village)."""
    log.warning("%s: restarting Clash of Clans", why)
    bot.save_error("stuck")
    bot.device.close_game()
    control.sleep(3)
    bot.device.launch_game()
    control.sleep(5)


def go_home(bot, timeout=60.0):
    """Get back to the home village from wherever the game is. Returns True on success.
    The game closed or crashed is started again; an unknown screen or a dialog the bot cannot answer
    for STUCK_RESTART seconds makes it restart the game (once per call)."""
    end = time.monotonic() + timeout
    live_since = None
    unknown = 0
    chest_taps = 0
    last = None
    last_ocr = 0.0
    loaded_after = None         # the Reload / Try Again tap after which the game was seen loading
    stuck_since = None          # since when the screen is unknown / an unanswerable dialog
    running_checked = 0.0
    restarted = False
    while time.monotonic() < end:
        frame = bot.shot()
        state = detect(frame)
        now = time.monotonic()
        if state != last:
            log.debug("screen: %s", state)
            last = state
            if state not in ("unknown", "reload"):
                stuck_since = None
        if state in ("unknown", "reload"):
            stuck_since = stuck_since or now
            if now - stuck_since > RUNNING_CHECK and now - running_checked > RUNNING_CHECK:
                running_checked = now
                if not bot.device.is_game_running():
                    log.warning("Clash of Clans is not running (closed or crashed): starting it")
                    bot.device.launch_game()
                    stuck_since, end = None, max(end, now + 120)
                    control.sleep(5)
                    continue
            if now - stuck_since > STUCK_RESTART and not restarted:
                _restart_now(bot, f"Stuck on an unknown screen for {STUCK_RESTART} s")
                restarted, stuck_since, end = True, None, max(end, time.monotonic() + 120)
                continue
        if bot.reloaded and state not in ("home", "reload"):
            loaded_after = bot.reload_at            # the game is loading again after that tap
        if state == "home" and tutorial_bubble(frame):
            dismiss_tutorial(bot, frame)             # a tutorial over the village: close it first
            continue
        if state == "home":
            if bot.reloaded:
                # right after the tap the old picture is still there: wait until it really reloaded
                if loaded_after != bot.reload_at and time.monotonic() - bot.reload_at < 10:
                    control.sleep(0.45)
                    continue
                after_reload(bot)
            return True
        if state == "unknown":
            unknown += 1
            if unknown % 3 == 0:     # give animations a moment before tapping blindly
                _close_any_popup(bot, frame)
        else:
            unknown = 0
        if state == "maintenance":
            wait_maintenance(bot, frame)
            end = time.monotonic() + timeout
            continue
        if state == "live_replay":
            if live_since is None:
                live_since = time.monotonic()
                log.info("Someone is attacking this village right now (live replay): waiting until it ends")
            if time.monotonic() - live_since < LIVE_REPLAY_MAX:
                end = max(end, time.monotonic() + 20)  # the attack ends by itself: never tap into it
            control.sleep(3)
            continue
        if state in ("exit_dialog", "wall_dialog"):
            bot.tap_point("dialog.cancel")           # never quit the game / never pay for walls by accident
        elif state in ("switcher", "settings", "army"):
            # its X where its picture is (BlueStacks draws these windows elsewhere than the PC), else the PC's point
            key = {"switcher": "sid/close", "settings": "settings/close", "army": "army/close"}[state]
            m = vision.templates.has(key) and vision.find(frame, key)
            if m:
                bot.tap_match(m, jitter=2)
            else:
                bot.tap_point({"switcher": "sid.close", "settings": "settings.close", "army": "army.close"}[state],
                              jitter=2)
        elif state == "attack_menu":
            bot.tap_point("attack_menu.close")
        elif state == "scout":
            bot.tap_point("scout.end_battle")
        elif state == "battle":
            surrender(bot)
        elif state == "confirm":
            bot.tap_template("battle/confirm_okay", timeout=1)
        elif state == "results":
            for k in ("results/claim_reward", "results/return_home"):
                m = vision.templates.has(k) and vision.find(frame, k)
                if m:
                    bot.tap_match(m)
                    break
        elif state == "chest":
            if chest_taps < CHEST_TAPS:
                end = max(end, now + 15)              # a big chest gives its rewards one by one: progress, not stuck
            # Skip (the new reward screens, e.g. "Clan Castle Slice"): every reward at once - the game asks "Skip
            # Chest opening? You'll receive the Reward" -> Yes; else Continue
            m = vision.templates.has("chest/skip_title") and vision.find(frame, "chest/skip_title")
            if m:
                yes = vision.find(frame, "chest/skip_yes")
                if yes:
                    bot.tap_match(yes, jitter=2)
                    log.info("Reward screen: skipped (the rewards are kept)")
                    control.sleep(1.2)
                    continue
            m = vision.templates.has("chest/skip") and vision.find(frame, "chest/skip")
            if m:
                bot.tap_match(m, jitter=2)
                chest_taps += 1
                log.info("Reward screen: Skip")
                control.sleep(1.0)
                continue
            m = vision.templates.has("chest/continue") and vision.find(frame, "chest/continue")
            if m:
                bot.tap_match(m)
                chest_taps += 1
                log.debug("Chest: Continue (reward %d)", chest_taps)
                control.sleep(0.8)
            else:
                # each tap breaks one lock; taps during the shake animation are ignored, so wait
                # between taps and rotate between the chest, above it and the side of the room
                spots = [(960, 600), (960, 420), (1830, 420), (960, 600), (700, 700)]
                bot.tap(*space.center(*spots[chest_taps % len(spots)]), jitter=12)
                chest_taps += 1
                control.sleep(0.6)
        elif state == "donate":
            bot.tap_point("donate.close", jitter=3)
        elif state == "chat":
            bot.tap_point("chat.close", jitter=2)
        elif state in ("lab_window", "upgrade_window"):
            m = None
            for key in ("lab/close", "upgrade/close"):
                m = vision.templates.has(key) and vision.find(frame, key)
                if m:
                    break
            if m:
                bot.tap_match(m, jitter=1)          # never the Finish Now (gems / magic item) buttons
            else:
                _tap_empty(bot, frame)
        elif state == "welcome_back":
            m = vision.find(frame, "popup/okay_big")    # (only under this title: a big green Okay elsewhere could
            if m:                                       #  confirm something)
                bot.tap_match(m, jitter=3)
            else:
                log.info("Welcome Back box: its Okay was not found")
        elif state == "remove_dialog":
            bot.tap_point("dialog.cancel")
        elif state == "request_window":
            bot.tap_point("request.cancel")
        elif state == "shop":
            m = vision.find(frame, "shop/close") if vision.templates.has("shop/close") else None
            bot.tap_match(m, jitter=1) if m else bot.tap_point("shop.close", jitter=0)
        elif state == "reward_popup":
            m = vision.templates.has("popup/continue_green") and vision.find(frame, "popup/continue_green")
            bot.tap_match(m) if m else bot.tap_point("popup.shield_continue")
        elif state == "shield_info":
            m = vision.templates.has("popup/shield_continue") and vision.find(frame, "popup/shield_continue")
            bot.tap_match(m) if m else bot.tap_point("popup.shield_continue")
        elif state == "bb_home":
            # in the Builder Base but the home village is wanted: sail back
            from . import village
            try:
                village.travel_home(bot)
            except Exception as e:  # noqa: BLE001
                log.warning("Could not sail back from the Builder Base: %s", e)
        elif state == "daily":
            # the X only works after claiming today's reward
            m = vision.templates.has("popup/daily_claim") and vision.find(frame, "popup/daily_claim")
            if m:
                bot.tap_match(m)
            else:
                bot.tap_point("popup.close_x", jitter=2)
        elif state == "dialog":
            if not dismiss_tutorial(bot, frame):
                bot.tap(*space.center(1300, 300), jitter=10)     # next line of the conversation
            control.sleep(0.4)
            continue
        elif state == "reload":
            tapped = press_reload(bot, frame)                      # Try Again / Reload by their pictures
            if not tapped and time.monotonic() - last_ocr > 2.5:
                last_ocr = time.monotonic()
                tapped = system_dialog(bot, frame)                 # else read the dialog's buttons
            if tapped:
                if tapped != "close":
                    end = max(end, time.monotonic() + 90)          # never give up while it reconnects
                stuck_since = None
                control.sleep(1.0)
        control.sleep(0.45)
    bot.save_error("not-home")
    return False


def ensure_game(bot, timeout=150.0):
    """Start the game with ADB if needed and wait for the home village."""
    dev = bot.device
    if not dev.is_game_running():
        log.info("Starting Clash of Clans...")
        dev.launch_game()
        start = time.monotonic()
        while not dev.is_game_running():
            if time.monotonic() - start > 60:
                raise BotError("Clash of Clans did not start")
            control.sleep(0.5)
    dev.tidy_up()
    if not go_home(bot, timeout):
        raise BotError("Could not reach the home village")
    return True


def restart_game(bot):
    """Restart the game where the device backend supports it; GPG PC must be reopened manually."""
    if getattr(bot.device, "kind", "") == "google_play_games":
        log.warning("Google Play Games cannot be restarted programmatically. Leaving it open and returning to the village.")
        ensure_game(bot)
        return
    log.warning("Restarting Clash of Clans")
    bot.device.close_game()
    control.sleep(8)
    ensure_game(bot)
