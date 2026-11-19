"""Settings and accounts, stored as JSON in config/ (edit them with any text editor).

  config/settings.json      what the bot does (see README.md); missing keys use the defaults below
  config/accounts.json      your accounts in the game's Supercell ID list order: name, Town Hall, enabled
  config/attack_plans.json  how troops are deployed
  config/state.json         written by the bot (where each account is in the account list)
"""

import copy
import json
import os
import threading

from . import paths

SETTINGS_PATH = os.path.join(paths.CONFIG, "settings.json")
ACCOUNTS_PATH = os.path.join(paths.CONFIG, "accounts.json")
STATE_PATH = os.path.join(paths.CONFIG, "state.json")

RESOURCES = ("gold", "elixir", "dark")

# Full storage per Town Hall: an account is full when its resource reaches this amount.
DEFAULT_FULL_AT = {
    "19": {"gold": 40500000, "elixir": 40500000, "dark": 500000},
    "18": {"gold": 30500000, "elixir": 30500000, "dark": 480000},
    "17": {"gold": 27500000, "elixir": 27500000, "dark": 440000},
    "16": {"gold": 25500000, "elixir": 25500000, "dark": 400000},
    "15": {"gold": 22500000, "elixir": 22500000, "dark": 380000},
    "14": {"gold": 20500000, "elixir": 20500000, "dark": 360000},
    "13": {"gold": 17500000, "elixir": 17500000, "dark": 340000},
    "12": {"gold": 14000000, "elixir": 14000000, "dark": 300000},
    "11": {"gold": 8000000, "elixir": 8000000, "dark": 200000},
}

# The loot a scouted base must have before it is attacked, by the attacking account's Town Hall
# ("default" for every Town Hall not in the list).
DEFAULT_MIN_LOOT = {
    "19": {"gold": 0, "elixir": 1200000, "dark": 0},
    "18": {"gold": 0, "elixir": 1200000, "dark": 0},
    "17": {"gold": 0, "elixir": 1000000, "dark": 0},
    "16": {"gold": 0, "elixir": 800000, "dark": 0},
    "15": {"gold": 0, "elixir": 800000, "dark": 0},
    "14": {"gold": 0, "elixir": 800000, "dark": 0},
    "13": {"gold": 0, "elixir": 800000, "dark": 0},
    "12": {"gold": 0, "elixir": 800000, "dark": 0},
    "11": {"gold": 0, "elixir": 500000, "dark": 0},
    "default": {"gold": 0, "elixir": 1200000, "dark": 0},
}

DEFAULT_SETTINGS = {
    "device": {
        "backend": "bluestacks",             # "bluestacks" or "google_play_games"
        "bluestacks_instance": "",          # "" = the main BlueStacks instance (Pie64); clones are Pie64_1 ...
        "adb_path": "",                     # "" = adb on PATH, else BlueStacks' own HD-Adb.exe
    },
    "mode": "loot",                         # "loot" / "raid" (Clan Capital raids) / "raid_loot" (raids, then loot)
    #                                         / "loot_donate" (the main account donates to your accounts' requests)
    #                                         / "loot_upgrade" (loot, and start upgrades with the free builders)
    #                                         / "loot_walls" (loot until full, then put the loot into walls)
    "start_from": 1,                        # account # (in accounts.json) the run starts with; follows the run
    "repeat_rounds": 1,                     # rounds over all accounts; 0 = loop forever
    "when_done": "nothing",                 # once every account is done: "nothing" / "close_game" /
    #                                         "close_bluestacks" / "close_all" (BlueStacks and the bot) / "lock"
    #                                         (close the game, lock the PC) / "shutdown" (close all, shut the PC down)
    "another_device_wait": 0,               # "Another device is connecting": minutes before Reload (0 = at once)
    "loot": {
        "watch": {"gold": False, "elixir": True, "dark": False},   # resources that decide "full"
        "full_rule": "any",                 # account is full when "any" / "all" watched resources are full
        "min_loot_rule": "any",             # attack when "any" / "all" watched resources reach the minimum
        "max_searches": 150,                # give up searching after this many "Next" (then retry)
        "max_attacks_per_account": 0,       # 0 = no limit
        "battle_seconds": 60,               # max battle time: end the battle after this many seconds
        "end_when_loot_stops": 15,          # end it sooner when no loot came in for this many seconds (0 = off)
        "smart_deploy": True,               # find the red no-deploy area and drop troops just outside it
        "count_troops": True,               # read each troop count and tap exactly that many times
        "attack_plan": "edrag_clone",       # a plan in config/attack_plans.json
        "auto_4x_speed": True,               # enable 4x once its control appears during an active battle
        "zoom_out": True,
        "stuck_attacks": 2,                 # resource did not grow after this many attacks -> treat as full
        # the army: before the first attack of each visit, Saved Recipes -> the first recipe (bot/army.py)
    },
    "raid": {
        "attacks": 6,                       # raid attacks per account per Raid Weekend (5, 6 with the bonus)
    },
    "walls": {                              # Loot + walls (bot/walls.py)
        "spend": {"gold": True, "elixir": True},  # walls may be paid with
        "keep": {"gold": 500000, "elixir": 500000},   # never spent (gold: searching for bases costs it)
    },
    "upgrade": {                            # Loot + upgrade (bot/upgrade.py)
        "spend": {"gold": True, "elixir": True, "dark": True},   # resources upgrades may be paid with
        "keep": {"gold": 500000, "elixir": 0, "dark": 0},        # never spent (gold: searching for bases costs it)
        "order": "game",                    # "game": the game's order, unticked ones skipped; "mine": only ticked
        #                                     ones, the highest in the list first
        "list": [],                         # [{"name", "on"}] in your order; buildings it does not name are added
        #                                     at its end (ticked; heroes unticked) - see bot/upgrade.py CATALOG
    },
    "donate": {                             # Loot + donate (bot/donate.py)
        "main": 1,                          # account # that donates (and loots when its elixir runs low)
        "partner": 2,                       # account # that always loots with the main one, and requests first
        "request_top": 30,                  # the top this many accounts of the list take part: 30 = the main
        #                                     account and the 29 below it request (ticks do not matter)
        "need": 4000000,                    # elixir the main account needs for a round of donations (40 lakh)
        "empty_cc": True,                   # empty the Clan Castle before requesting
        "only_mine": False,                 # donate only to requests from your own accounts
        "big_template": "donate/super_wizard",   # in colour in the donate window = a big request
        # what the main account donates, in this order: "use" big / small / all requests; "clicks" = taps when
        # the request's room cannot be read (else exactly what fits)
        "items": [
            {"name": "Balloon", "template": "donate/balloon", "category": "troop", "space": 5, "clicks": 12,
             "use": "big"},
            {"name": "Archer", "template": "donate/archer", "category": "troop", "space": 1, "clicks": 9,
             "use": "all"},
            {"name": "Lightning", "template": "donate/lightning", "category": "spell", "space": 1, "clicks": 3,
             "use": "all"},
            {"name": "Stone Slammer", "template": "donate/stone_slammer", "category": "siege", "space": 1,
             "clicks": 2, "use": "all"},
        ],
    },
    "full_at": DEFAULT_FULL_AT,
    "min_loot": DEFAULT_MIN_LOOT,
    "hotkeys": {"pause": "f9", "stop": "f10"},
    "save_error_screenshots": True,
}

WHOLE = ("full_at", "min_loot")          # tables taken as written (not merged with the defaults)


def _merge(defaults, data):
    out = copy.deepcopy(defaults)
    for k, v in (data or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in WHOLE:
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


_lock = threading.Lock()


def load_settings():
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            settings = _merge(DEFAULT_SETTINGS, json.load(f))
    else:
        settings = copy.deepcopy(DEFAULT_SETTINGS)

    # Preserve existing user settings after the Root Rider + Valkyrie plan was renamed.
    if settings["loot"].get("attack_plan") == "TH17 - Root Rider + Valkyrie":
        settings["loot"]["attack_plan"] = "root_valk"
    return settings


def save_settings(settings):
    with _lock, open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def save_accounts(accounts):
    """One account per line, keys without "_" (those are only for the current run)."""
    clean = [{k: v for k, v in a.items() if not k.startswith("_")} for a in accounts]
    with _lock, open(ACCOUNTS_PATH, "w", encoding="utf-8") as f:
        f.write("[\n" + ",\n".join("  " + json.dumps(a) for a in clean) + "\n]\n")


def load_accounts():
    """[{"name", "th", "enabled", "full_at"?}] in the game's Supercell ID list order."""
    if not os.path.exists(ACCOUNTS_PATH):
        raise RuntimeError("config/accounts.json is missing: list your accounts there (see README.md)")
    with open(ACCOUNTS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for a in data:
        if not str(a.get("name", "")).strip():
            continue
        acc = {"enabled": True, "th": 0}
        acc.update(a)
        acc["th"] = int(acc.get("th") or 0)
        out.append(acc)
    return out


def full_at(settings, account, resource):
    """The amount at which `resource` counts as full for this account:
    1. the account's own "full_at" in accounts.json, else
    2. the "full_at" table in settings.json for the account's Town Hall."""
    own = (account.get("full_at") or {}).get(resource, 0)
    if own:
        return own
    table = settings.get("full_at", DEFAULT_FULL_AT)
    th = str(account.get("th") or "")
    if th in table:
        return table[th].get(resource, 0)
    return 0   # unknown -> never "full" by value (the stuck-attack rule still applies)


def min_loot(settings, account):
    """The loot a base needs for this account: by its Town Hall, else the "default" row."""
    table = settings.get("min_loot", DEFAULT_MIN_LOOT)
    th = str(account.get("th") or "")
    return table.get(th) or table.get("default") or {}


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {}


def save_state(state):
    with _lock, open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
