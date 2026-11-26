"""The run: open each enabled account in turn and loot it until its storages are full, use its Clan Capital
raid attacks, or both (settings "mode": loot / raid / raid_loot), or loot and start upgrades with the free builders
(loot_upgrade, bot/upgrade.py) - or Loot + donate (loot_donate, bot/donate.py).

Errors are recovered from (screenshot, back to the village, retry; the game restarted with ADB
when that does not help), so one stuck screen never ends a long run.
"""

import logging
import threading
import time

from . import account as account_actions
from . import config, donate, loot, net, raid, upgrade, vision, walls
from .context import Bot, BotError
from .control import BotStopped, Stuck, control, is_user_abort
from .device import BlueStacksDevice, GooglePlayGamesDevice
from .states import ensure_game, go_home, restart_game

log = logging.getLogger("bot")

MAX_AUTO_RESTARTS = 20
STUCK_AFTER = 240       # seconds on one step (not a wait, not paused): the watchdog makes the bot recover


def setup_logging(debug=False, console=True):
    """Everything (debug too) to logs/bot.log; info and up (or everything with debug) to the console."""
    import os
    import sys

    from . import paths
    if console:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
        h.setLevel(logging.DEBUG if debug else logging.INFO)
        log.addHandler(h)
    f = logging.FileHandler(os.path.join(paths.LOGS, "bot.log"), encoding="utf-8")
    f.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
    f.setLevel(logging.DEBUG)
    log.addHandler(f)
    log.setLevel(logging.DEBUG)
REQUIRED = ["home/build_button", "home/dark_drop", "attack_menu/find_match", "army/attack_button",
            "army/my_army_title", "army/close", "scout/next", "scout/end_battle", "battle/surrender",
            "results/return_home", "settings/title", "settings/switch_id", "sid/switch_id_label"]


def make_bot(settings, accounts):
    missing = [k for k in REQUIRED if not vision.templates.has(k)]
    if missing:
        raise RuntimeError("Missing template images in assets/templates: " + ", ".join(missing))
    if not vision.digits.ready:
        raise RuntimeError("Digit images are missing in assets/digits")
    d = settings["device"]
    backend = d.get("backend", "bluestacks")
    if backend == "google_play_games":
        device = GooglePlayGamesDevice(adb_path=d.get("adb_path", ""))
    elif backend == "bluestacks":
        device = BlueStacksDevice(d.get("bluestacks_instance", ""), d.get("adb_path", ""))
    else:
        raise RuntimeError(f"Unknown device backend: {backend}")
    bot = Bot(device, settings, accounts)
    bot.state = config.load_state()
    return bot


def with_recovery(bot, label, fn, attempts=3):
    """Run fn(); on errors save a screenshot, get the game back to the village and retry.
    A network outage does not use up attempts: the bot waits for the internet and tries again."""
    attempt, outages = 0, 0
    while attempt < attempts:
        attempt += 1
        try:
            return fn()
        except BotStopped:
            raise
        except Exception as e:  # noqa: BLE001 - any failure: recover and retry
            if is_user_abort(e):
                raise BotStopped("the mouse touched a screen corner (emergency stop)") from e
            if isinstance(e, (BotError, Stuck)):
                log.warning("%s: %s (attempt %d/%d)", label, e, attempt, attempts)
            else:
                log.exception("%s: unexpected error (attempt %d/%d)", label, attempt, attempts)
            bot.save_error(label.replace(" ", "-"))
            if outages < 20 and net.wait_until_online():
                outages += 1
                attempt -= 1                           # not the action's fault: does not count
                go_home(bot, 120)                      # taps the game's Try Again until it is back
                continue
            try:
                if attempt == attempts - 1 or not bot.device.is_game_running() or not go_home(bot, 45):
                    restart_game(bot)
            except BotStopped:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Recovery failed")
    log.error("%s: giving up after %d attempts", label, attempts)
    return None


RESULTS = {"full": "storages full", "stuck": "storages full (stopped growing)", "limit": "attack limit reached",
           "no_army": "no army with the required units", "no_gold": "not enough gold to search"}


def loot_account(bot, acc):
    """Switch to the account and loot it until full. Its result goes to bot.progress (shown in the window):
    full / stuck / limit / no_army / no_gold, or "skipped" when it could not be opened or looted."""
    progress = bot.progress.setdefault(acc["name"], {})
    progress["status"] = "looting"
    if not with_recovery(bot, f"switch to {acc['name']}", lambda: account_actions.switch_to(bot, acc)):
        log.error("Skipping %s: could not switch to it", acc["name"])
        bot.progress.setdefault(acc["name"], {})["status"] = "skipped"
        return None

    def run():
        if bot.current_account != acc["name"]:        # a reload opened another account meanwhile
            account_actions.switch_to(bot, acc)
        return loot.loot_until_full(bot, acc)

    result = with_recovery(bot, f"loot {acc['name']}", run)
    bot.progress.setdefault(acc["name"], {})["status"] = result or "skipped"
    if result:
        log.info("%s: %s", acc["name"], RESULTS.get(result, result))
    return result


MODES = {"loot": "Loot all accounts", "raid": "Clan Capital raids", "raid_loot": "Raids, then loot",
         "loot_upgrade": "Loot + upgrade", "loot_walls": "Loot + walls", "loot_donate": "XpIncrease",
         "donate_only": "Donate + loot (PC 1)", "request_only": "Request only (PC 2)"}


def raid_account(bot, acc):
    """Switch to the account and use its raid attacks (bot.progress: "raided" / "raid_none" / "skipped")."""
    progress = bot.progress.setdefault(acc["name"], {})
    progress["status"] = "raiding"
    if not with_recovery(bot, f"switch to {acc['name']}", lambda: account_actions.switch_to(bot, acc)):
        log.error("Skipping %s: could not switch to it", acc["name"])
        progress["status"] = "skipped"
        return

    def run():
        if bot.current_account != acc["name"]:
            account_actions.switch_to(bot, acc)
        return raid.run(bot, acc, int(bot.settings.get("raid", {}).get("attacks", 6) or 6))

    made = with_recovery(bot, f"raid {acc['name']}", run, attempts=2)
    progress["status"] = "skipped" if made is None else "raided" if made else "raid_none"


def upgrade_account(bot, acc):
    """Switch to the account and start upgrades with its free builders (bot.progress: "upgrades" counted; the status
    goes back to what it was)."""
    p = bot.progress.setdefault(acc["name"], {})
    before = p.get("status")
    p["status"] = "upgrading"

    def run():
        if bot.current_account != acc["name"]:
            account_actions.switch_to(bot, acc)
        return upgrade.spend(bot, acc)

    n = with_recovery(bot, f"upgrade {acc['name']}", run, attempts=2)
    if before not in (None, "upgrading"):
        p["status"] = before                           # (the loot result stays)
    else:
        p["status"] = "skipped" if n is None else "upgraded" if n else "no_upgrade"
    return n or 0


def walls_account(bot, acc):
    """Put the account's loot above what is kept into walls (bot.progress: "walls" counted; the status goes back to
    what it was)."""
    p = bot.progress.setdefault(acc["name"], {})
    before = p.get("status")
    p["status"] = "walls"

    def run():
        if bot.current_account != acc["name"]:
            account_actions.switch_to(bot, acc)
        return walls.spend(bot, acc)

    n = with_recovery(bot, f"walls {acc['name']}", run, attempts=2)
    p["status"] = before if before not in (None, "walls") else "skipped" if n is None else "full"
    return n or 0


def walls_until_done(bot, acc):
    """Loot + walls on one account until its walls are done: walls with what is above the keep, loot until full,
    walls, loot until full, walls, ... The next account comes when full storages upgrade no wall (every wall is
    upgraded, the rest waits for a free builder, or one wall costs more than the storages hold above the keep), or
    when looting stops (no army, attack limit, no gold to search, the account could not be opened)."""
    name = acc["name"]
    total = walls_account(bot, acc)                    # what is already above the keep: room for the loot
    n = 0
    while True:                                        # no round limit: only the walls or the looting end it
        n += 1
        control.checkpoint()
        result = loot_account(bot, acc)
        done = walls_account(bot, acc) if result else 0
        total += done
        if result not in ("full", "stuck"):
            log.info("%s: looting stopped (%s) after %d wall(s) - next account", name,
                     RESULTS.get(result, result) if result else "the account could not be looted", total)
            return
        if not done:
            log.info("%s: %s - %d wall(s) upgraded on it, next account", name,
                     getattr(bot, "walls_note", "") or "no wall could be upgraded", total)
            return
        log.info("%s: loot + walls round %d: %d wall(s) upgraded (%d so far) - looting again", name, n, done, total)


def run_accounts(bot, start_from=1, rounds=1, mode="loot"):
    """Every enabled account in accounts.json order, from account #start_from; `rounds` times (0 = forever).
    Raids only happen on Raid Weekend; in "raid" mode an account without raid attacks left is not opened at
    all, and one pass is made. bot.start_from follows the run (the window shows it, the next run goes on
    from there) and is back at 1 after a whole round."""
    if mode == "loot_donate":
        donate.run(bot)                                # its own cycle, always from the main account
        return
    if mode == "donate_only":
        donate.run_donor(bot)                          # 2-PC Donor PC: donates & loots main account only
        return
    if mode == "request_only":
        donate.run_requester(bot)                      # 2-PC Requester PC: requests only in a loop
        return
    order = [(i, a) for i, a in enumerate(bot.accounts, 1) if a.get("enabled", True)]
    if not order:
        raise RuntimeError("No enabled accounts in config/accounts.json")
    weekend, when = raid.describe_window()
    raids, looting, upgrading = mode in ("raid", "raid_loot"), mode != "raid", mode == "loot_upgrade"
    walling = mode == "loot_walls"
    log.info("%s: %s", MODES.get(mode, mode),
             ", ".join(f"#{i} {a['name']} (TH {a.get('th') or '?'})" for i, a in order))
    if raids:
        log.info("%s%s", when, "" if weekend or looting else " - nothing to raid now")
        if not weekend and not looting:
            return
    rounds = 1 if not looting else rounds
    n = 0
    while rounds == 0 or n < rounds:
        n += 1
        log.info("Round %d%s", n, f" of {rounds}" if rounds else "")
        if n > 1:
            bot.progress.clear()                       # a new round: every account is looted again
        for pos, acc in order:
            if pos < start_from:
                continue
            control.checkpoint()
            raid_now = raids and raid.window()[0] and raid.pending(bot, acc["name"])
            if not raid_now and not looting:
                bot.progress.setdefault(acc["name"], {})["status"] = "raid_none"
                continue                               # nothing to do on it: not even opened
            bot.start_from = pos
            log.info("== #%d %s", pos, acc["name"])
            if raid_now:
                raid_account(bot, acc)
            if walling:
                walls_until_done(bot, acc)             # walls, loot, walls, loot ... on this account until done
                continue
            if upgrading:
                upgrade_account(bot, acc)              # spend first: room in the storages for the loot
            if looting:
                loot_account(bot, acc)
            if upgrading:
                upgrade_account(bot, acc)              # then what was looted
        start_from = bot.start_from = 1                # only the first round skips accounts


def loot_all(bot, start_from=1, rounds=1):
    run_accounts(bot, start_from, rounds, "loot")


def check(settings, accounts):
    """Start BlueStacks and the game, go to the village, read what the bot sees. No attack."""
    import os

    import cv2

    from . import paths, states
    from .device import screen_size
    from .space import space

    b = make_bot(settings, accounts)
    ensure_game(b)
    frame = b.shot()
    log.info("Screen %dx%d -> game space %dx%d", *screen_size(), space.w, space.h)
    log.info("Screen detected: %s", states.detect(frame))
    log.info("Resources: %s", loot._fmt(loot.home_resources(b)))
    path = os.path.join(paths.LOGS, "check.png")
    cv2.imencode(".png", frame)[1].tofile(path)
    log.info("What the bot sees: %s", path)
    log.info("Accounts: %s", ", ".join(f"{a['name']} (TH {a.get('th') or '?'})" for a in accounts
                                         if a.get("enabled", True)))


# once every account is done (not after Stop): what the settings' "when_done" says
AFTER_RUN = {"nothing": "Do nothing", "close_game": "Close Clash of Clans", "close_bluestacks": "Close BlueStacks",
             "close_all": "Close BlueStacks and the bot", "lock": "Close Clash of Clans and lock the PC",
             "shutdown": "Shut the PC down"}
SHUTDOWN_DELAY = 60     # seconds Windows counts down before it shuts down (cancel: shutdown /a)


def after_run(bot, what):
    """Close the game / BlueStacks, lock the PC or shut it down, as the settings say. Shut down: Clash of Clans and
    BlueStacks are closed first (BlueStacks until its window is gone), then Windows is told to shut down in
    SHUTDOWN_DELAY s; the bot window closes itself for "close_all" and "shutdown" (window.py)."""
    if what not in AFTER_RUN or what == "nothing":
        return
    log.info("All accounts done - %s", AFTER_RUN[what])
    try:
        game_closed = bot.device.close_game()
        if game_closed is False:
            log.info("Clash of Clans left open (this device backend cannot close it safely)")
        else:
            log.info("Clash of Clans closed")
        if what in ("close_bluestacks", "close_all", "shutdown"):
            emulator_closed = bot.device.close_bluestacks()
            if emulator_closed is False:
                log.info("Emulator left open (this device backend does not manage the emulator process)")
            else:
                log.info("Emulator closed")
    except Exception:  # noqa: BLE001 - the PC is still locked / shut down
        log.exception("Closing the game / BlueStacks failed")
    if what == "lock":
        import ctypes
        ctypes.windll.user32.LockWorkStation()
    elif what == "shutdown":
        import subprocess
        subprocess.run(["shutdown", "/s", "/t", str(SHUTDOWN_DELAY), "/c",
                        "COC Bot: every account is done - the PC shuts down."], capture_output=True)
        log.warning("The PC shuts down in %d s (to keep it on: Win+R, then  shutdown /a)", SHUTDOWN_DELAY)


def restart_only(settings, accounts):
    """The Restart button: BlueStacks up, Clash of Clans closed and opened again, back on the village. No attack."""
    b = make_bot(settings, accounts)
    if b.device.is_game_running():
        restart_game(b)
    else:
        ensure_game(b)
    log.info("Clash of Clans restarted: on the village")


def close_bluestacks_only(settings, accounts):
    """The Close emulator button (BlueStacks is not started for it)."""
    if settings.get("device", {}).get("backend", "bluestacks") == "google_play_games":
        log.info("Google Play Games is left open; this button only applies to BlueStacks.")
        return
    from .device import BlueStacks, close_bluestacks
    bs = BlueStacks.find()
    if not bs:
        raise RuntimeError("BlueStacks 5 is not installed on this PC")
    title = bs.instance(settings["device"].get("bluestacks_instance", ""))["title"]
    log.info("BlueStacks %s", "closed" if close_bluestacks(title) else "is not open")


def _screen_now(bot, label):
    """A screenshot without touching BlueStacks (from the watchdog's thread)."""
    try:
        import cv2
        import numpy as np
        from PIL import ImageGrab
        bot.save_error(label, cv2.cvtColor(np.asarray(ImageGrab.grab()), cv2.COLOR_RGB2BGR))
    except Exception:  # noqa: BLE001 - only a picture for the log
        pass


def watchdog(bot, done):
    """While the run lasts: one step that takes longer than STUCK_AFTER (not a wait, not while paused) is logged
    with a screenshot, and the bot is made to recover from it (back to the village; the game is restarted when that
    does not help) - a stuck screen never ends a long run."""
    while not done.wait(10):
        if control.paused:
            bot.action_at = time.monotonic()
            continue
        idle = time.monotonic() - bot.action_at
        if idle > STUCK_AFTER and not bot.action.startswith(("Waiting", "Starting")):
            log.warning("No progress for %d min on '%s' (%s) - recovering", idle // 60, bot.action,
                        bot.current_account or "no account yet")
            _screen_now(bot, "stuck")
            bot.action_at = time.monotonic()
            control.kick(f"no progress for {int(idle // 60)} min on '{bot.action}'")


def run(settings, accounts, start_from=None, rounds=None, on_bot=None):
    """The whole run: BlueStacks up, the game started (ADB), every account looted / raided (settings "mode"),
    then the 'when done' action. on_bot(bot) is called once the bot exists (the window shows its account and
    counters)."""
    started = time.time()
    bot = None
    reason = "finished"
    finished = threading.Event()
    start_from = start_from or int(settings.get("start_from", 1) or 1)
    rounds = settings.get("repeat_rounds", 1) if rounds is None else rounds
    mode = settings.get("mode", "loot")
    try:
        bot = make_bot(settings, accounts)
        bot.start_from = start_from
        if on_bot:
            on_bot(bot)
        threading.Thread(target=watchdog, args=(bot, finished), daemon=True, name="watchdog").start()
        restarts = 0
        while True:
            try:
                ensure_game(bot)
                run_accounts(bot, start_from, rounds, mode)
                break
            except BotStopped:
                raise
            except Exception as e:  # noqa: BLE001 - keep a long run alive: restart the game and go on
                if is_user_abort(e) or restarts >= MAX_AUTO_RESTARTS:
                    raise
                restarts += 1
                log.exception("Unexpected error; restarting the game and continuing (%d/%d)",
                              restarts, MAX_AUTO_RESTARTS)
                bot.save_error("crash")
                if bot.current_acc:                    # go on with the account it was on
                    start_from = bot.accounts.index(bot.current_acc) + 1
                try:
                    net.wait_until_online()            # no point restarting without internet
                    restart_game(bot)
                except BotStopped:
                    raise
                except Exception:  # noqa: BLE001
                    log.exception("Game restart failed; trying again in 30 s")
                    control.sleep(30)
        after_run(bot, settings.get("when_done", "nothing"))
    except BotStopped as e:
        reason = "stopped"
        log.info("Stopped: %s", e.args[0] if e.args else "Stop pressed")
    except Exception as e:  # noqa: BLE001
        if is_user_abort(e):
            reason = "stopped"
            log.info("Stopped (mouse moved into a screen corner)")
        else:
            reason = "error"
            log.exception("The bot stopped because of an error")
            if bot:
                bot.save_error("crash")
    finally:
        finished.set()
        mins = (time.time() - started) / 60
        stats = bot.stats if bot else {"attacks": 0, "searches": 0, "loot": {}}
        log.info("Run %s after %.0f min. Attacks: %s, raid attacks: %s, searches: %s, upgrades: %s, requests: %s, "
                 "units donated: %s, loot gained: %s", reason, mins, stats["attacks"], stats.get("raids", 0),
                 stats["searches"], stats.get("upgrades", 0), stats.get("requests", 0), stats.get("donated", 0),
                 ", ".join(f"{r} {v:,}" for r, v in stats["loot"].items()) or "-")
    return reason
