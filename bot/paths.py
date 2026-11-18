"""Runtime paths for source runs and PyInstaller builds.

In a frozen build, immutable assets live in PyInstaller's bundle directory
(sys._MEIPASS), while editable config and logs live beside the executable.
"""
import os
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
