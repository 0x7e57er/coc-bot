"""BlueStacks 5 on this PC, full screen at the PC's own screen resolution.

  * ADB is used only to start and stop Clash of Clans (and to see whether it runs).
  * Pictures are taken of the screen itself (ImageGrab), the images are found on them, and the
    mouse clicks / drags those screen pixels (BlueStacks full screen and in front).
  * Zooming out uses BlueStacks' own zoom key for Clash of Clans: the Down arrow (its game controls).

The screen is whatever resolution Windows uses right now; the bot scales it into "game space"
(space.py). Set BlueStacks' own resolution (Settings > Display) to the same size as the screen so
full screen has no black bars.
"""

import logging
import os
import shutil
import subprocess
import time

import cv2
import numpy as np
import win32api
import win32con
import win32gui

from .control import control
from .space import space

log = logging.getLogger("bot")

COC_PACKAGE = "com.supercell.clashofclans"


def screen_size():
    """The current Windows screen resolution in real pixels (the process is DPI aware)."""
    return win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)


def find_adb(preferred=""):
    for p in (preferred, shutil.which("adb"), r"C:\platform-tools\adb.exe"):
        if p and shutil.which(p):
            return shutil.which(p)
    return None


def bring_to_front(hwnd):
    """Make `hwnd` the foreground window. Returns True on success."""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.4)
    if win32gui.GetForegroundWindow() != hwnd:
        # Windows only lets the foreground process hand over focus; a synthetic
        # Alt press lifts that restriction for our process.
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        finally:
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.15)
    return win32gui.GetForegroundWindow() == hwnd


class BlueStacks:
    """BlueStacks 5 as installed on this PC: its programs, and its instances as written in its own
    settings file (bluestacks.conf): name, window title, ADB port and screen size."""

    def __init__(self, install_dir, data_dir):
        self.player = os.path.join(install_dir, "HD-Player.exe")
        self.adb = os.path.join(install_dir, "HD-Adb.exe")
        self.conf = os.path.join(data_dir, "bluestacks.conf")

    @classmethod
    def find(cls):
        """The installed BlueStacks 5, or None."""
        import winreg
        install, data = r"C:\Program Files\BlueStacks_nxt", r"C:\ProgramData\BlueStacks_nxt"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\BlueStacks_nxt", 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                install = winreg.QueryValueEx(k, "InstallDir")[0]
                data = winreg.QueryValueEx(k, "UserDefinedDir")[0]
        except OSError:
            pass
        bs = cls(install, data)
        return bs if os.path.exists(bs.player) and os.path.exists(bs.conf) else None

    def _values(self):
        out = {}
        with open(self.conf, encoding="utf-8", errors="replace") as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                out[key] = value.strip('"')
        return out

    def adb_enabled(self):
        return self._values().get("bst.enable_adb_access") == "1"

    def instances(self):
        """[{"name", "title", "port", "size"}], the main instance (Pie64, Nougat64 ...) before its clones."""
        per = {}
        for key, value in self._values().items():
            if key.startswith("bst.instance."):
                name, _, field = key[len("bst.instance."):].partition(".")
                per.setdefault(name, {})[field] = value
        found = []
        for name, v in per.items():
            port = v.get("status.adb_port") or v.get("adb_port")     # status.* = where it runs right now
            if not port or not port.isdigit():
                continue
            try:
                size = (int(v["fb_width"]), int(v["fb_height"]))
            except (KeyError, ValueError):
                size = None
            found.append({"name": name, "title": v.get("display_name") or name, "port": int(port), "size": size})
        found.sort(key=lambda i: ("_" in i["name"], i["name"]))      # clones are Pie64_1, Pie64_2 ...
        return found

    def instance(self, name=""):
        """The instance called `name`; empty = the main one."""
        found = self.instances()
        if not found:
            raise RuntimeError("BlueStacks has no instance yet: open BlueStacks once")
        for i in found:
            if not name or i["name"] == name:
                return i
        raise RuntimeError(f"BlueStacks instance '{name}' not found (there are: " +
                           ", ".join(i["name"] for i in found) + "): set device.bluestacks_instance in "
                           "config/settings.json")

    def start(self, name):
        subprocess.Popen([self.player, "--instance", name], close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def close_bluestacks(title):
    """Close the BlueStacks instance whose window title starts with `title` (its own process only). Returns True
    when one was open. Works without the bot's device (which would start BlueStacks)."""
    import win32process
    found = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h).startswith(title):
            found.append(h)

    win32gui.EnumWindows(cb, None)
    for hwnd in found:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=20,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    end = time.monotonic() + 20                       # until its window is really gone
    while found and any(win32gui.IsWindow(h) for h in found) and time.monotonic() < end:
        time.sleep(0.5)
    if any(win32gui.IsWindow(h) for h in found):
        log.warning("BlueStacks did not close")
    return bool(found)


class BlueStacksDevice:
    """BlueStacks 5 on this PC, always full screen and in front. The bot takes a picture of the screen
    itself, finds the images on it and clicks those screen pixels with the mouse. ADB only starts and
    stops Clash of Clans. The instance and its ADB port come from BlueStacks' own settings; BlueStacks is
    started when it is not running, and put in full screen (its F11) whenever it is not."""

    kind = "bluestacks"
    BOOT_SECONDS = 150
    ui_scale = 1.2              # measured at 1920x1080 with 160 and 240 DPI: every button 1.2x the PC picture
    field_scale = 0.89          # village border at full zoom-out: half-width 656 game-space px vs the PC's 734
    # full-screen windows (game space, measured at 1920x1080): (size of the PC picture, centre this much lower)
    windows = ((0.928, -4),     # the army screen (the first: its points in layout.py use it)
               (0.833, 0))      # the battle results: pixel for pixel the PC picture on the screen

    def __init__(self, instance="", adb_path="", package=COC_PACKAGE):
        import pyautogui
        from pynput.keyboard import Controller, Key

        pyautogui.PAUSE = 0.05
        pyautogui.FAILSAFE = True   # slam the mouse into a screen corner to abort
        self._pg = pyautogui
        self._kb = Controller()
        self._Key = Key
        self._native = None
        self._hwnd = None
        self.bs = BlueStacks.find()
        if not self.bs:
            raise RuntimeError("BlueStacks 5 is not installed on this PC")
        self.inst = self.bs.instance(instance)
        # the PC's own adb first: two adb versions keep restarting each other's server
        self.adb = find_adb(adb_path) or self.bs.adb
        self.serial = f"127.0.0.1:{self.inst['port']}"
        self.package = package
        self.connect()

    def describe(self):
        title = self.inst["title"]
        return f"{title if 'bluestacks' in title.lower() else 'BlueStacks ' + title} (full screen)"

    # --- ADB: start and stop only --------------------------------------------------------
    def _run(self, *args, timeout=15):
        try:
            r = subprocess.run([self.adb, "-s", self.serial, *args], capture_output=True, timeout=timeout,
                               creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            return ""
        return r.stdout.decode(errors="replace")

    def _booted(self):
        try:                                # (short timeouts: Stop waits for the call in progress)
            subprocess.run([self.adb, "connect", self.serial], capture_output=True, timeout=6,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            return False
        return self._run("shell", "getprop", "sys.boot_completed", timeout=6).strip() == "1"

    def connect(self):
        """BlueStacks running (started when it is not), Android booted and the window full screen."""
        if not self._booted():
            if not self.bs.adb_enabled():
                raise RuntimeError("ADB is off in BlueStacks: switch it on in BlueStacks Settings > Advanced > "
                                   "Android Debug Bridge (the bot starts and stops the game with it)")
            for attempt in (1, 2):
                log.info("Starting BlueStacks (%s)...", self.inst["name"])
                self.bs.start(self.inst["name"])
                end = time.monotonic() + self.BOOT_SECONDS
                while not self._booted() and time.monotonic() < end:
                    control.sleep(3)                     # (Stop is seen here, not after the 150 s)
                    self.inst = self.bs.instance(self.inst["name"])      # the port can change when it starts
                    self.serial = f"127.0.0.1:{self.inst['port']}"
                if self._booted():
                    break
                if attempt == 2 or not self.find_window():
                    raise RuntimeError(f"BlueStacks did not start within {self.BOOT_SECONDS} s")
                # its window is there but Android does not answer: BlueStacks is frozen (seen 2026-11-20: the
                # screen stood still and every start waited 150 s again) - closed and started again
                log.warning("BlueStacks is open but does not answer (frozen?): closing it and starting it again")
                self._hwnd = None
                close_bluestacks(self.inst["title"])
                control.sleep(3)
            log.info("BlueStacks is up")
        self.full_screen()
        sw, sh = screen_size()
        log.info("Using %s on the %dx%d screen (ADB %s)", self.describe(), sw, sh, self.serial)
        if self.inst["size"] and self.inst["size"] != (sw, sh):
            log.warning("BlueStacks' own resolution is %dx%d but the screen is %dx%d: set BlueStacks to %dx%d "
                        "(BlueStacks Settings > Display) so its full screen fills the screen exactly",
                        *self.inst["size"], sw, sh, sw, sh)

    def is_game_running(self):
        """Running and on screen (in front of other Android apps)."""
        if not self._run("shell", "pidof", self.package).strip():
            return False
        top = self._run("shell", "dumpsys activity activities | grep -m 1 -E 'topResumedActivity|mResumedActivity'")
        return self.package in top

    def launch_game(self):
        """Start the game, or bring it to the front of BlueStacks (BlueStacks first, when it was closed)."""
        if not self._booted():
            self.connect()
        self._run("shell", "monkey", "-p", self.package, "-c", "android.intent.category.LAUNCHER", "1")

    def close_game(self):
        self._run("shell", "am", "force-stop", self.package)

    def close_bluestacks(self):
        """Close this BlueStacks instance (not other instances)."""
        self._hwnd = None
        return close_bluestacks(self.inst["title"])

    def tidy_up(self):
        self.full_screen()

    # --- the window: always full screen --------------------------------------------------
    def find_window(self):
        if self._hwnd and win32gui.IsWindow(self._hwnd):
            return self._hwnd
        found = []

        def cb(h, _):
            if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h).startswith(self.inst["title"]):
                found.append(h)

        win32gui.EnumWindows(cb, None)
        self._hwnd = found[0] if found else None
        return self._hwnd

    def is_full_screen(self):
        hwnd = self.find_window()
        if not hwnd or win32gui.IsIconic(hwnd):
            return False
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        return (left, top, right - left, bottom - top) == (0, 0, *screen_size())

    def full_screen(self):
        """Put the BlueStacks window in full screen (its F11) if it is not. Raises when that fails."""
        end = time.monotonic() + 30
        while not self.find_window():                    # the window comes a moment after Android
            if time.monotonic() > end:
                raise RuntimeError(f"BlueStacks window '{self.inst['title']}' not found")
            control.sleep(1)
        for _ in range(3):
            if self.is_full_screen():
                return
            log.info("Putting BlueStacks in full screen")
            if not bring_to_front(self.find_window()):
                control.sleep(2.0)                       # F11 would go to the window in front: not now
                continue
            self._kb.press(self._Key.f11)
            self._kb.release(self._Key.f11)
            control.sleep(2.0)
        if not self.is_full_screen():
            raise RuntimeError("BlueStacks is not in full screen: press F11 in BlueStacks")

    def prepare(self):
        """BlueStacks full screen and in front: the screen is then the game. While another window keeps the
        focus (you are using the PC) the bot waits: it never looks at or clicks on another window."""
        if not self.is_full_screen():
            self.full_screen()
        warned = False
        while win32gui.GetForegroundWindow() != self.find_window():
            if bring_to_front(self.find_window()):
                break
            if not warned:
                log.warning("BlueStacks is not in front (another window has the focus): waiting. Press F9 to "
                            "pause the bot while you use the PC.")
                warned = True
            control.sleep(2)
        if warned:
            log.info("BlueStacks is in front again: going on")
            time.sleep(0.5)

    # --- pictures ---------------------------------------------------------------------------
    def _capture_native(self):
        """The screen itself, as the monitor shows it."""
        from PIL import ImageGrab
        self.prepare()
        return cv2.cvtColor(np.asarray(ImageGrab.grab()), cv2.COLOR_RGB2BGR)

    def capture(self):
        """A screenshot in game space (see space.py)."""
        frame = self._capture_native()
        h, w = frame.shape[:2]
        self._native = (w, h)
        gw, gh = space.update(w, h, self.ui_scale, self.field_scale, self.windows)
        if (w, h) != (gw, gh):
            interp = cv2.INTER_AREA if w > gw else cv2.INTER_LINEAR
            frame = cv2.resize(frame, (gw, gh), interpolation=interp)
        return frame

    def to_native(self, x, y):
        if self._native is None:
            self.capture()
        return round(x * space.scale), round(y * space.scale)

    # --- mouse and keyboard (game-space coordinates) ----------------------------------------
    def tap(self, x, y):
        self.prepare()
        self._pg.click(*self.to_native(x, y))

    def tap_burst(self, x, y, n, interval=0.05):
        """Tap the same spot n times as fast as the game takes them (a card's whole stack)."""
        self.prepare()
        a, b = self.to_native(x, y)
        for i in range(n):
            if i:
                time.sleep(interval)
            self._pg.click(a, b, _pause=False)

    def swipe(self, x1, y1, x2, y2, ms=500):
        """Press, move, pause, release (the view stops where the mouse stops)."""
        self.prepare()
        self._pg.moveTo(*self.to_native(x1, y1))
        self._pg.mouseDown()
        try:
            time.sleep(0.08)
            self._pg.moveTo(*self.to_native(x2, y2), duration=ms / 1000)
            time.sleep(0.08)
        finally:
            self._pg.mouseUp()

    def drag(self, x1, y1, x2, y2, ms=500):
        """Like swipe, but released while still moving (no pause at either end), exactly like the
        old completeid/XpIncrease scroll: on the Supercell ID list one drag moves exactly 4 rows."""
        self.prepare()
        self._pg.moveTo(*self.to_native(x1, y1))
        self._pg.mouseDown()
        try:
            self._pg.moveTo(*self.to_native(x2, y2), duration=ms / 1000)
        finally:
            self._pg.mouseUp()

    def zoom_out(self, presses=2):
        """BlueStacks' Zoom control for Clash of Clans (its game controls): holding the Down arrow pinches two
        fingers together, and one press zooms out completely. The mouse wheel goes to the game instead and
        stops halfway."""
        for _ in range(presses):
            self.prepare()                               # the key goes to the window in front: BlueStacks
            self._kb.press(self._Key.down)
            time.sleep(0.4)
            self._kb.release(self._Key.down)
            time.sleep(0.4)
