"""COC bot package.

Make the process DPI aware before anything asks Windows for coordinates,
otherwise the screen size, screenshots and clicks are scaled by the display zoom (125% here).
"""

import ctypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
except Exception:
    pass
