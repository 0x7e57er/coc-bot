"""Runtime paths for source runs and PyInstaller builds.

In frozen builds, read-only assets and defaults are inside the PyInstaller bundle
(sys._MEIPASS). Editable config and logs live beside the executable.
"""
import os
import shutil
import sys

if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(os.path.abspath(sys.executable))
    RESOURCE_ROOT = getattr(sys, "_MEIPASS", ROOT)
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    RESOURCE_ROOT = ROOT

ASSETS = os.path.join(RESOURCE_ROOT, "assets")
TEMPLATES = os.path.join(ASSETS, "templates")       # <group>/<name>.png + index.json (search region, threshold)
TEMPLATE_INDEX = os.path.join(TEMPLATES, "index.json")
DIGITS = os.path.join(ASSETS, "digits")             # the game's digit images (0-9)
CONFIG = os.path.join(ROOT, "config")
LOGS = os.path.join(ROOT, "logs")
ERROR_SHOTS = os.path.join(LOGS, "errors")

for _d in (CONFIG, LOGS, ERROR_SHOTS):
    os.makedirs(_d, exist_ok=True)

# The one-file executable unpacks read-only files into a temporary _MEIPASS
# directory. Seed the writable config with the bundled presets on first run,
# while preserving any attack plans the user has already edited.
_BUNDLED_ATTACK_PLANS = os.path.join(RESOURCE_ROOT, "config", "attack_plans.json")
_USER_ATTACK_PLANS = os.path.join(CONFIG, "attack_plans.json")
if os.path.isfile(_BUNDLED_ATTACK_PLANS) and not os.path.exists(_USER_ATTACK_PLANS):
    shutil.copy2(_BUNDLED_ATTACK_PLANS, _USER_ATTACK_PLANS)
