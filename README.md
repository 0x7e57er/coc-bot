# COC bot: loot, upgrade, raid and donate with all accounts

A small Clash of Clans bot for **BlueStacks 5** and **Google Play Games for PC**, written in Python. It opens each of your
accounts in turn and either:

- **Loot**: loots it until its storages are full;
- **Capital raid**: uses its Clan Capital raid attacks (Raid Weekend only);
- **Raid + loot**: does both, raid attacks first;
- **Loot + upgrade**: starts upgrades with its free builders, loots until full, then upgrades again;
- **Loot + walls**: puts the gold and elixir above what you keep into walls (both resources), loots until
  full, then does it again.

Then it goes on to the next account. Or:

- **Loot + donate**: your accounts request troops and your main account donates to them, paying with
  elixir; when the main account's elixir runs low it loots, and your partner account loots with it.

- **BlueStacks 5:** ADB starts/stops Clash of Clans; desktop screenshots and mouse input drive the bot.
- **Google Play Games for PC:** the bot captures the game's `CROSVM` window surface and sends mouse
  messages directly to that window. The game window may sit behind other apps, but must not be minimized.
  This mode does not require ADB.
- The bot scales screenshots into its game coordinate space; BlueStacks remains full-screen while
  Google Play Games can run in a normal window.

## Setup (once)

1. Install Python 3.10+ (tick "Add python.exe to PATH") and run `setup.bat`.
2. In **Loot settings → Device**, choose the backend you use:
   - **Google Play Games for PC:** open Clash of Clans first. Keep its window open and unminimized; it may sit
     behind other applications. No ADB setup is needed. The bot currently does not launch/restart/close the
     consumer Google Play Games client, so open the game yourself before pressing Start.
   - **BlueStacks 5:** continue with the BlueStacks settings below; ADB must be enabled.
3. In BlueStacks 5 settings:
   - **Advanced > Android Debug Bridge**: on.
   - **Display**: set the resolution to the same size as your Windows screen (for example
     1920×1080), so BlueStacks full screen fills the screen with no black bars.
   - Keep BlueStacks' **game controls** for Clash of Clans. The Down arrow is its zoom-out key, and
     the bot uses it.
4. Put your accounts in `config/accounts.json`, in the **same order as the game's Supercell ID list**:

   ```json
   [
     {"name": "Buggu01", "th": 18, "enabled": true},
     {"name": "Omishrisha", "th": 16, "enabled": true},
     {"name": "Buggu8", "th": 11, "enabled": false}
   ]
   ```

   - `name`: the account name as the Supercell ID list shows it.
   - `th`: the account's Town Hall level. It picks the full storage and the minimum loot below. If
     it is `0`, the bot reads it from the account list.
   - `enabled`: `false` means this account is skipped.
   - Optional `"full_at": {"elixir": 20000000}`: this account's own full amount, which overrides the
     table.

5. In every account, put your looting army (E-Dragons and Clone spells) **first** in Saved Recipes. The
   bot presses Use on the top recipe of the Saved Recipes tab before the first attack on each account.

## Windows executable

The Windows build is a **single-file executable**: `COC-Bot.exe`. The Python runtime, libraries,
game image assets and default attack-plan presets are bundled inside it. There is no `_internal`
folder and no separate runtime files to keep beside the executable.

- **GitHub Actions:** open Actions -> **Build Windows executable** -> Run workflow. Download the
  `COC-Bot-Windows-x64` artifact and extract it once; the extracted contents are just
  `COC-Bot.exe`. Version tags such as `v1.0.0` publish the EXE itself as a release asset.
- **Locally:** install Python 3.10+ and run `build-windows.bat`. The single executable is created at
  `dist/COC-Bot.exe`.

On first launch, the app creates writable `config` and `logs` folders beside the EXE. The default
attack-plan presets are copied into `config/attack_plans.json` automatically. Put your own
`config/accounts.json` there (or add accounts in the app) and save settings as usual. Keep those
folders if you want to preserve your setup and logs; they are runtime data, not extra files required
to launch the EXE.

The executable is a Windows x64 GUI build. It does not bundle BlueStacks or Android. One-file builds
take a little longer to start because Windows unpacks the bundled runtime into a temporary folder.
Install the selected emulator on the target PC. ADB is required only for BlueStacks 5, not Google Play
Games for PC.

## Run

Double-click `run.bat` (or `python main.py`). The window opens maximized. It has a sidebar and a
top bar with **Save**, **Check setup** (starts the game and reads the resources, without
attacking), **Start**, **Pause (F9)** and **Stop (F10)**. Its pages:

- **Dashboard**:
  - **What to run**: Loot, Capital raid, Raid + loot, Loot + upgrade or Loot + donate. The choice is saved
    at once.
  - **Start from account**: the account the run starts with. It follows the run, so it always shows
    the account the bot is on, and after a stop the next run goes on from there. After a whole round
    it is back at the first account. You can change it whenever the bot is stopped. Loot + donate does
    not use it: it always starts on the main account.
  - Whether Raid Weekend is on, and how long it lasts, or when the next one starts.
  - **Now**: the account, its Town Hall and its place in the list, the action (searching, battle,
    raid attack 2 on Wizard Valley ...), how full the account is, and the last base's loot.
  - **This run**: attacks, raid attacks, searches, run time, loot gained and accounts done (in Loot +
    donate: requests sent and units donated instead of raid attacks and accounts done).
  - Every ticked account's status this run (waiting / looting / full / raided / requested / donated ...).
  - Recent activity.
- **Accounts**: tick, name, Town Hall and an optional own full elixir. You can search, add, remove,
  move and tick all. Keep the game's list order.
- **Loot settings**: run, when an account is full, choosing a base, Loot + donate, battle, army, Loot +
  upgrade, Clan Capital raid and device. Each setting is explained under its name.
- **Storage & loot**: full storage and minimum loot per Town Hall.
- **Log**: the whole log, the log file and the error screenshots. **Every step (detailed)** (the default)
  also shows each step the bot starts ("Step: Searching #3"), each screen it sees and each decision, in
  grey. **Main events** shows only the main lines, **Warnings and errors** only problems. The log file
  `logs/bot.log` always has everything.

Save (Ctrl+S) writes everything to `config/`, and Start saves too. The settings pages are locked
while the bot runs. Pages slide in, the sidebar highlight glides, numbers count up, bars fill
smoothly, and short notices appear at the bottom right.

Without the window:

```
python main.py --start              the window, with Start pressed at once
python main.py --cli                loot every enabled account until full, in the console
python main.py --cli --from 5       start with account #5 of accounts.json
python main.py --cli --rounds 0     keep going round the accounts forever
python main.py --cli --mode raid    Clan Capital raids in the console (or loot / raid_loot / loot_upgrade /
                                    loot_donate)
python main.py --check              only check the setup, and save what the bot sees to logs/check.png
```

- **F9**: pause / continue. **F10**: stop. Pushing the mouse into a screen corner also stops the bot.
  When a run ends (F10 too), the window comes back in front of BlueStacks.
- The mouse is busy while the bot runs, because it clicks on BlueStacks. To use the PC, press F9
  first. If another window takes the front anyway, the bot waits and never clicks on it.

## The flow (copied from Coc-Bot's "Loot all accounts")

1. BlueStacks is started if it is not running and put in full screen (F11). Clash of Clans is
   started with ADB (`monkey`) and the bot waits for the home village. Popups, chests, results,
   tutorials, "Try Again" / "Reload", maintenance breaks and the Builder Base are all handled on
   the way back to the village.
2. **Switch account**: profile picture > Settings > Switch ID. One 0.5 s drag moves the list exactly 4
   accounts, so the bot drags straight to the account's page. It reads the names there and taps the
   right one.
3. **Full?** The bot reads gold, elixir and dark elixir on the village. An account is full when the
   watched resource (elixir by default) reaches `full_at` for its Town Hall in `settings.json`. If
   the storages stop growing for 2 attacks, the account also counts as full.
4. **Army**: before the first attack: Battle > Edit Army > the **Saved Recipes** tab > **Use** on the first
   (top) recipe. The game asks to confirm only when the Clan Castle has troops; then the bot presses Okay. If
   there is no recipe to use, the account attacks with the army it has, and the log says so.
5. **Search**: Attack > Find a Match > Attack!. Then it presses Next until a base has at least the
   `min_loot` for this account's Town Hall. The loot numbers are read with the game's own digit
   images. It gives up after 150 searches.
6. **Attack** (`edrag_clone` plan): the bot finds the base's buildings and puts a deploy ring just
   outside the red area. It reads the troop bar by what its cards are, not by their place. Cards with
   an "x11" count left of the heroes are troops; cards without a count are the siege machine and the
   heroes; cards with a count after them are spells; the empty slots are skipped. So any army works.
   The troops go down in 3 groups (left, top, right), with a Clone cast on each group as it lands. Then
   the siege machine and every hero go behind the groups, then the other spells on the troops' way.
   Every tap is checked against the card. A spot that does not deploy is moved and tried again.
7. **End**: the battle is surrendered when none of the loot left in the base (gold, elixir and dark
   elixir) has gone down for `end_when_loot_stops` seconds. Troops busy on gold mines still count as
   looting. At the latest it ends after `battle_seconds` (60). Then the bot goes home and starts again from
   step 3 until the account is full, and then moves to the next account.

## Clan Capital raid (Raid Weekend: Friday 07:00 to Monday 07:00 UTC)

For each ticked account that still has raid attacks:

1. The village is zoomed out and swiped so the Clan Capital airship shows. Its red badge
   ("5 ⚔") says how many raid attacks are left. Each village's scenery puts the airship somewhere else,
   so up to five views are looked at, and the one where it was found is remembered for that account.
   With no badge in any view, the account has no raid attack left (looked at again on the next run). A tap
   that misses the airship is noticed within 4 s. If the Capital does not open 3 times, the account is
   skipped for the rest of the weekend.
2. The airship is tapped. Any popup in the Capital is closed, and the "New Raid" banner of a raid that
   just began is passed with its Go. The Raid Map button's badge is read again to confirm.
3. **On the account's first raid attack only**: Change Capital Army. All units are deleted, then as
   many Super Miners as fit, 1 Frost and 2 Graveyard are added, and the army is saved. If it already
   is that army, it is left as it is.
4. **Raid Map**: the map's labels are read: each district's name, its destruction ("100%" =
   destroyed) and "Locked". Destroyed and locked districts are never tapped. Districts already being
   attacked (1-99 %) come first, then the others from Barbarian Camp on. The map is read at its top,
   then swiped down for the districts not seen there. The tapped district's bar must show a **red**
   Attack (a grey one = destroyed: the bar is closed and the next one is tried). The log shows what
   the map says ("Raid map (top): Barbarian Camp 100%, ... Builder's Workshop 0%").
5. **Attack**: zoomed out completely and moved fully down and right, so the camera is always at the
   same place. Each district's free deploy spot is found once and remembered: the deepest spot of the
   pale green strip the game lights up along the district's edge (then a wider colour look, then spots
   around the middle of the screen, one by one). A spot counts only when the Super Miner card turns
   grey, so a wrong spot is never learned, and a learned spot that stops working is found again.
   Every later attack on that district taps that spot at once with all the Super Miners (as many taps
   as the card's "x10"). The spells go into the district, up and left of the miners; if the miners did
   not go out, no spell is used.
6. As soon as everything is deployed, Clash of Clans is **closed and opened again with ADB**. The
   battle goes on without the bot waiting for it, and the next raid attack starts right away.

Learned places are kept in `config/state.json`. **Loot settings > Clan Capital raid > Forget**
clears them, and they are then found again.

## Loot + upgrade

Each ticked account, in turn: upgrades, then loots until full, then upgrades again with the new loot.
Upgrading:

1. The **Build** button (bottom right) opens "Buildings & Heroes": the upgrades in progress, then
   "Suggested upgrades" and "Other upgrades", each with its cost.
2. The rows are read and matched to **your list** (Loot settings > Loot + upgrade). It has every building
   of the game. Tick what may be upgraded, and drag it (or Up / Down) into your order. You can also add
   names the game has that the list does not. **Choose upgrades by**:
   - **The game's order**: the first row the account can pay, as the game lists it (suggested first),
     unticked ones skipped;
   - **My list, top first**: only ticked ones. The whole Build list is read (scrolled to its end), and the
     highest one in your list that the account can pay is upgraded.

   Only resources you let it spend are used, and 5 lakh gold is always kept for searching. The Town Hall
   and heroes start unticked: after a Town Hall upgrade, change its level on the Accounts page. Walls are
   never upgraded.
3. Its upgrade window opens. The green **Confirm** is tapped only when it shows exactly that cost. The
   grey "Hammer of Building" (a magic item) is never used.
4. Again while builders are free. At the end the storages are read again, and the log shows what was
   really spent.

**Never with gems.** The builders tab ("1/7") also counts the Goblin Builder, who costs gems. So when every
real builder is busy, the game answers Confirm with "Hey Chief! ... all your Builders are busy" (Goblin
Builder / Free a Builder, both gems). The bot closes that box with its X and stops upgrading on that
account. It also reads the time left on the upgrades in progress and does not open the Build panel on
that account again until the first one is done.

## Loot + walls

Each ticked account first puts what is already above what you keep into walls (room for the loot), loots
until full, then does it again. What may be spent is set in **Loot settings > Loot + walls**: pay with gold /
elixir, always keep 5 lakh of each. Walls go cheapest first, with **both** resources:

- gold pays for every wall level; the higher levels also take elixir (two Upgrade buttons, same price);
- on a level that takes both, the resource that pays for more walls goes first, then the other one pays for the
  walls left of that level;
- only elixir to spend: the gold-only levels are skipped and the elixir levels are upgraded; only gold: every
  level can use it;
- which levels take which resource is remembered per account, so a visit whose loot pays for no wall does not
  open the list;
- since the November 2026 update the higher walls need a **free builder**. When the game answers "Hey Chief!
  Looks like all your Builders are busy", the box is closed with its X (never the gem button), and walls of that
  level and up wait until the first upgrade in progress is done. The cheaper levels still go on.

Each batch:

1. The Build panel lists the walls by level, for example "Wall x 25 - 1,000" (25 walls, 1,000 each).
   The list is read once per visit, about 50 s. The account's cheapest wall is remembered, so a visit
   that cannot pay even that one does not open the list.
2. The wall row is tapped: one wall of that level is selected. Then the game's **Upgrade More**.
3. **Add Wall** (+10, +1) until the walls the budget pays for are selected. The count is read after
   every tap.
4. **Upgrade** with the chosen resource. The total on the button must be a whole number of walls, within
   what may be spent, and match the count in the title.
5. "Upgrade Walls - ... for 50000 Gold?" -> **Okay** only when the box asks exactly that amount of that
   resource. Otherwise, or when its Okay does not show, Cancel: the box is never left open. Never gems.
6. The walls count only when the storage on screen really went down by that amount.

Walls upgrade at once (no builder). The log shows each level done and the storages before and after.

## Loot + donate

Set it up in **Loot settings > Loot + donate**: the main account (#1), the partner (#2), how many accounts
from the top of the list take part ("Request troops from the top": 30 = the main account and the 29 below
it; ticks do not matter here), and the elixir one round of donations needs (40 lakh). Then choose
**Loot + donate** on the Dashboard and press Start. It does not use "Start from account".

1. The main account is opened and its elixir read.
2. **Enough elixir**: the partner, then the other accounts of the top 30, in turn:
   army screen (Battle > Edit Army) > the Clan Castle's trash > Okay (empties it) > Request > Send.
3. The main account is opened again: clan chat > each request's Donate > Balloons for big requests,
   Archers for the room left, Lightning, a Stone Slammer (exactly what fits when the request's room
   can be read). Back to 1.
4. **Not enough elixir**: the main account loots until full, then the partner loots until full, and
   the requests start again with the partner (step 2).

It goes on until you stop it.
- The clan's request cooldown is read from the Request button after each request. If a round is
  shorter than the cooldown, the bot waits on the main account until the partner can request again.
- An account still on cooldown when its turn comes is passed over for that round, unless its cooldown
  ends within a minute: then the bot waits for it.
- If the donate window charges gems, nothing is donated (set the game's "Donation Resource" back to
  elixir).
- What is donated is the list `donate.items` in `config/settings.json`.

**When every account is done** (Loot settings > Run; not after Stop): do nothing, close Clash of Clans, close
BlueStacks, close BlueStacks and the bot, close the game and lock the PC, or shut the PC down.

**Shut the PC down**:
1. Clash of Clans is closed.
2. BlueStacks is closed, and the bot waits until its window is gone.
3. Windows is told to shut down 1 minute later.
4. The bot closes itself.

To keep the PC on during that minute: Win+R, then `shutdown /a`.

**Loot settings > Device > Now**: **Restart the game** (closes Clash of Clans and opens it again, back to the
village; BlueStacks is started if it is closed) and **Close BlueStacks**.

**Problems handled on the way:**

- **Stuck**: a watchdog looks at what the bot is doing. One step that makes no progress for 4 minutes
  (not a wait, not paused) is logged as a warning with a screenshot (`logs/errors/...-stuck.png`).
  The bot is then made to recover: back to the village, and the game is restarted when that does not
  help. So a stuck screen never ends a long run.
- **Big reward chests**: every Continue counts as progress, so a chest with many rewards is opened to its
  end instead of being taken for a stuck game.
- **Reward screens** (since the November 2026 update, e.g. "Clan Castle Slice - Item delivered to the
  Temporary Storage"): **Skip**, then **Yes** in "Skip Chest opening? You'll receive the Reward". The
  rewards are kept.
- **Items Delivered** (a white box after a store gift or purchase): **OKAY**.

- **Dialogs**: any dark dialog of the game or of Android is read and answered:
  - Connection lost / network failed: **Try Again**, once the internet is back.
  - Another device opened the account: **Reload** - at once, or after the minutes set in **Loot settings > Run >
    Another device plays this account**, so you can play on your phone meanwhile.
  - Idle too long: **Reload Game**.
  - "Rate Clash of Clans": **Never**.
  - Otherwise: Later, Cancel or Okay. It never presses Review, Exit or Update, and on "Confirm Exit"
    only Cancel.
- **Game closed or crashed**: started again with ADB.
- **Stuck**: an unknown screen, or a dialog with no button it may press, for 60 s: the game is
  restarted with ADB.
- **Maintenance**: it waits for the time the maintenance break shows.
- **Live replay**: if someone is attacking the village, it waits until the attack is over.
- **Builder Base**: if an account opens there, it sails back home.
- **Big windows** (army screen, battle results): BlueStacks draws them smaller than the PC pictures,
  so the bot also looks for the pictures at those sizes.

Every problem saves a screenshot in `logs/errors/`. Everything is logged in `logs/bot.log`.

## settings.json

| Key | Meaning |
|---|---|
| `device.bluestacks_instance` | `""` = the main BlueStacks instance; clones are `Pie64_1` ... |
| `device.adb_path` | `""` = adb on PATH, else BlueStacks' own HD-Adb.exe |
| `mode` | `"loot"`, `"raid"` (Clan Capital raids), `"raid_loot"` (raids, then loot), `"loot_upgrade"`, `"loot_walls"` or `"loot_donate"` |
| `start_from` | account # the run starts with; it follows the run (where it stopped) |
| `repeat_rounds` | rounds over all accounts, `0` = forever |
| `when_done` | once every account is done (not after Stop): `"nothing"`, `"close_game"`, `"close_bluestacks"`, `"close_all"` (BlueStacks and the bot), `"lock"` (close the game, lock the PC) or `"shutdown"` (close the game and BlueStacks, shut the PC down 1 minute later, the bot closes itself; to keep the PC on: `shutdown /a`) |
| `another_device_wait` | minutes to wait before Reload when another device plays the account (`0` = at once) |
| `loot.watch` | which resources decide "full" (elixir by default) |
| `loot.full_rule` | `"any"` / `"all"` watched resources full |
| `loot.min_loot_rule` | attack when `"any"` / `"all"` watched resources reach the minimum |
| `loot.max_searches` | Next presses before giving up the search |
| `loot.max_attacks_per_account` | `0` = no limit |
| `loot.battle_seconds` | the battle is ended after this many seconds at the latest |
| `loot.end_when_loot_stops` | end it sooner when no loot came in for this many seconds (`0` = off) |
| `loot.smart_deploy` | deploy on a ring just outside the base (else the plan's fixed points) |
| `loot.count_troops` | read each card's count and check every tap |
| `loot.attack_plan` | a plan in `attack_plans.json` (`edrag_clone`, `edrag_spread`) |
| `loot.stuck_attacks` | storages not growing after this many attacks = full |
| `raid.attacks` | raid attacks per account per Raid Weekend (`6`) |
| `walls.spend` / `walls.keep` | Loot + walls: resources walls may be paid with (gold, elixir) and what is never spent (`500000` each) |
| `upgrade.spend` | resources upgrades may be paid with (`gold`, `elixir`, `dark`: all on) |
| `upgrade.keep` | never spent (`gold: 500000`: searching costs gold) |
| `upgrade.order` | `"game"` (the game's order, unticked ones skipped) or `"mine"` (only ticked, top of the list first) |
| `upgrade.list` | `[{"name", "on"}]` in your order; buildings it does not name are added at its end (ticked; Town Hall and heroes unticked) |
| `donate.main` / `donate.partner` | account # of the main account (`1`, donates) and its partner (`2`, `0` = none) |
| `donate.request_top` | the top this many accounts take part (`30` = the main account and 29 requesters) |
| `donate.need` | elixir the main account needs for a round (`4000000` = 40 lakh); below it, it loots |
| `donate.empty_cc` | empty the Clan Castle before requesting (`true`) |
| `donate.only_mine` | donate only to requests from your own accounts (`false` = every request) |
| `donate.items` | what is donated, in order: picture, housing space, taps, `use` big / small / all requests |
| `full_at` | full storage per Town Hall: `{"18": {"gold": ..., "elixir": ..., "dark": ...}}` |
| `min_loot` | loot a base must have, per Town Hall (`"default"` for the others) |

## Files

- `bot/device.py`: BlueStacks: starts and stops the game with ADB, takes screenshots, and moves the
  mouse and keys.
- `bot/space.py`, `bot/layout.py`: map any screen resolution onto the 1920×1080 pictures and points.
- `bot/vision.py`: finds images on the screen, reads the game's digits, and reads text (account names).
- `bot/states.py`: detects which screen the game is on and gets back to the village.
- `bot/account.py`: switches accounts.
- `bot/army.py`: the army screen, and the first saved recipe before looting.
- `bot/loot.py`: decides when an account is full, searches for a base, attacks, and loots until full.
- `bot/attack.py`, `bot/deployzone.py`: deploy troops and end the battle.
- `bot/raid.py`: Clan Capital raids: the airship, the capital army, the districts, deploying, restarting.
- `bot/walls.py`: Loot + walls: the wall rows of the Build panel, Upgrade More, Add Wall, the checked Okay.
- `bot/upgrade.py`: Loot + upgrade: the Build panel, choosing an upgrade it can pay, the safe Confirm.
- `bot/donate.py`: Loot + donate: emptying the Clan Castle, requesting, donating from the clan chat,
  and the loot / request / donate cycle.
- `bot/runner.py`: the all-accounts loop (loot / raid / both) and recovering from errors.
- `window.py`, `motion.py`, `icons.py`: the window (PySide6), its animations and its icons (the same
  set as Coc-Bot's).
- `assets/templates/`, `assets/digits/`: the pictures, copied from Coc-Bot (1920×1080), including the
  Clan Capital ones in `assets/templates/raid/` and the clan ones (chat, request, donate window).
