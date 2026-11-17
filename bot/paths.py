import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
TEMPLATES = os.path.join(ASSETS, "templates")       # <group>/<name>.png + index.json (search region, threshold)
TEMPLATE_INDEX = os.path.join(TEMPLATES, "index.json")
DIGITS = os.path.join(ASSETS, "digits")             # the game's digit images (0-9)
CONFIG = os.path.join(ROOT, "config")
LOGS = os.path.join(ROOT, "logs")
ERROR_SHOTS = os.path.join(LOGS, "errors")

for _d in (CONFIG, LOGS, ERROR_SHOTS):
    os.makedirs(_d, exist_ok=True)
