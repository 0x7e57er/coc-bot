"""COC bot: loot (and Clan Capital raid) with all your Clash of Clans accounts on BlueStacks.

    python main.py                    the window: accounts, settings, Start / Pause / Stop, live log
    python main.py --start            the window, and Start pressed at once
    python main.py --cli              loot every enabled account in config/accounts.json, in this console
    python main.py --cli --from 5     start with account #5 (its place in accounts.json)
    python main.py --cli --rounds 0   go round the accounts forever
    python main.py --cli --mode raid  Clan Capital raids (or loot / raid_loot / loot_upgrade / loot_walls /
                                      loot_donate / donate_only / request_only; default: the window's choice)
    python main.py --check            only check the setup: start the game, read the resources, save a screenshot

F9 pauses / continues, F10 stops. Pushing the mouse into a screen corner also stops it.
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bot  # noqa: E402,F401  (DPI awareness before anything asks Windows for sizes)
from bot import config, runner  # noqa: E402
from bot.control import control  # noqa: E402

log = logging.getLogger("bot")


def main():
    p = argparse.ArgumentParser(description="Loot all Clash of Clans accounts on BlueStacks")
    p.add_argument("--cli", action="store_true", help="run in this console, without the window")
    p.add_argument("--start", action="store_true", help="the window: press Start at once")
    p.add_argument("--from", dest="start_from", type=int, help="start with account #N of accounts.json")
    p.add_argument("--rounds", type=int, help="rounds over all accounts (0 = forever)")
    p.add_argument("--mode", choices=list(runner.MODES) + ["xpincrease"],
                   help="loot / raid / raid_loot / loot_upgrade / loot_walls / xpincrease (or loot_donate) / "
                        "donate_only / request_only (default: settings.json)")
    p.add_argument("--check", action="store_true", help="only check the setup (no attack)")
    p.add_argument("--debug", action="store_true", help="show every step in the console")
    args = p.parse_args()

    if not (args.cli or args.check):
        import window                                  # the window (default)
        sys.exit(window.main(start=args.start))

    runner.setup_logging(args.debug)
    settings = config.load_settings()
    accounts = config.load_accounts()
    keys = settings.get("hotkeys", {})
    control.start_hotkeys(keys.get("pause", "f9"), keys.get("stop", "f10"))
    log.info("F9 = pause / continue, F10 = stop (or push the mouse into a screen corner)")

    if args.check:
        runner.check(settings, accounts)
        return
    if args.mode:
        settings["mode"] = "loot_donate" if args.mode == "xpincrease" else args.mode
    reason = runner.run(settings, accounts, start_from=args.start_from, rounds=args.rounds)
    sys.exit(0 if reason in ("finished", "stopped") else 1)


if __name__ == "__main__":
    main()
