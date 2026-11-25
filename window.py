"""The COC Bot window (opens maximized).

  Dashboard      what to run (Loot / Raid / Raid + loot) and the account it starts from (it follows the run),
                 what the bot is doing now: account, action, how full it is, the last base, counters, every
                 account's status this run, recent activity
  Accounts       the accounts in the game's list order: tick, name, Town Hall, own full elixir
  Loot settings  when an account is full, which base to attack, the battle, the army, Capital raids, the device
  Storage & loot full storage and minimum loot per Town Hall
  Log            the whole log

Settings are saved to config/*.json (Save / Ctrl+S, and on Start). The bot runs in a background thread so the
window stays responsive; F9 pauses / continues and F10 stops it from anywhere. The animations are in motion.py.
"""

import collections
import ctypes
import json
import logging
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bot  # noqa: E402,F401  (DPI awareness before Qt starts)
from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QObject, QPropertyAnimation, QSize, Qt,  # noqa: E402
                            QTimer, Signal)
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut  # noqa: E402
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox,  # noqa: E402
                               QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import icons  # noqa: E402
import motion  # noqa: E402
from bot import attack, config, paths, raid, runner, upgrade  # noqa: E402
from bot.control import control  # noqa: E402

log = logging.getLogger("bot")

# ----------------------------------------------------------------------------- palette (Coc-Bot's)
BG, SIDEBAR, SURFACE, SURFACE_2, SURFACE_3 = "#0f1220", "#0b0e1a", "#161a2d", "#1c2139", "#262c4a"
INPUT, BORDER, BORDER_STRONG = "#121628", "#232944", "#323a5e"
TEXT, MUTED, DIM = "#e8ebf7", "#98a1c3", "#636c91"
GOLD, ELIXIR, DARK = "#f5b942", "#e27df6", "#a898ec"
GREEN, RED, AMBER, BLUE, ORANGE = "#2fc27a", "#ef4f5f", "#f5a524", "#5b8cff", "#ff9f43"
RES_COLOR = {"gold": GOLD, "elixir": ELIXIR, "dark": DARK}
RES_NAME = {"gold": "Gold", "elixir": "Elixir", "dark": "Dark elixir"}
RESOURCES = config.RESOURCES

# what a run does: (data, button text, icon, colour)
MODES = [("loot", "Loot", "swords", GREEN), ("raid", "Capital raid", "castle", ORANGE),
         ("raid_loot", "Raid + loot", "bolt", BLUE), ("loot_upgrade", "Loot + upgrade", "arrow-up", GOLD),
         ("loot_walls", "Loot + walls", "shield", AMBER),
         ("loot_donate", "Loot + donate (1 PC)", "users", ELIXIR),
         ("donate_only", "Donate + loot (PC 1)", "users", ELIXIR),
         ("request_only", "Request only (PC 2)", "flag", BLUE)]
DONATE_MODES = ("loot_donate", "donate_only", "request_only")
MODE_HELP = {"loot": "Every ticked account attacks until its storages are full",
             "raid": "Every ticked account uses its Clan Capital raid attacks (Raid Weekend only)",
             "raid_loot": "Each ticked account first uses its raid attacks (on Raid Weekend), then loots until full",
             "loot_upgrade": "Each ticked account starts upgrades with its free builders, loots until full, then "
                             "upgrades again with the loot",
             "loot_walls": "Each ticked account stays until its walls are done: walls with the gold and elixir "
                           "above what you keep, loot until full, walls, loot ... (cheapest first, both resources)",
             "loot_donate": "1 PC: your accounts request troops and the main account donates to them; when its elixir "
                            "runs low it loots until full, and the partner loots too",
             "donate_only": "2-PC Donor (PC 1): stays on the main account, keeps donating to open requests, and loots "
                            "until full when its elixir drops below the threshold (then donates right after)",
             "request_only": "2-PC Requester (PC 2): keeps requesting troops across the requesting accounts only "
                             "(never loots or donates; any unfilled previous request is replaced automatically)"}

# an account's status in this run -> (text, colour)
STATUS = {
    "waiting": ("Waiting", DIM),
    "looting": ("Looting", BLUE),
    "full": ("Full", GREEN),
    "stuck": ("Full (stopped growing)", GREEN),
    "limit": ("Attack limit", AMBER),
    "no_army": ("No army", RED),
    "no_gold": ("No gold to search", AMBER),
    "skipped": ("Skipped", RED),
    "raiding": ("Raiding", ORANGE),
    "raided": ("Raided", GREEN),
    "raid_none": ("No raid attacks", DIM),
    "requesting": ("Requesting", BLUE),
    "requested": ("Requested", GREEN),
    "cooldown": ("Request cooldown", DIM),
    "not_requested": ("Could not request", AMBER),
    "no_clan": ("Not in a clan", RED),
    "donating": ("Donating", ELIXIR),
    "donated": ("Donated", GREEN),
    "upgrading": ("Upgrading", GOLD),
    "upgraded": ("Upgraded", GREEN),
    "no_upgrade": ("No upgrade now", DIM),
    "walls": ("Upgrading walls", AMBER),
}
DONE = ("full", "stuck", "limit", "no_army", "no_gold", "skipped", "raided", "raid_none")
TOAST_ICON = {"info": "info", "success": "check-circle", "warning": "alert", "error": "x-circle"}

CHECK_SVG = os.path.join(paths.ASSETS, "ui", "check.svg").replace("\\", "/")

STYLE = f"""
* {{ font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QWidget#root, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {BG}; }}
QFrame#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#stat {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#stat:hover {{ border-color: {BORDER_STRONG}; background: {SURFACE_3}; }}
QFrame#navPill {{ background: {SURFACE_2}; border-radius: 9px; }}
QFrame#navEdge {{ background: {GOLD}; border-radius: 1px; }}
QFrame#segmented {{ background: {INPUT}; border: 1px solid {BORDER_STRONG}; border-radius: 11px; }}
QPushButton#seg {{ background: transparent; border: none; border-radius: 8px; padding: 7px 16px; color: {MUTED};
                   font-weight: 600; }}
QPushButton#seg:hover:!checked {{ color: {TEXT}; }}
QPushButton#seg:disabled {{ color: {DIM}; }}
QLabel#pill {{ border-radius: 11px; padding: 4px 12px; font-weight: 600; font-size: 9pt; }}
QFrame#banner {{ background: rgba(245, 165, 36, 0.12); border: 1px solid rgba(245, 165, 36, 0.45);
                border-radius: 8px; }}
QLabel {{ background: transparent; }}
QLabel#logo {{ color: {GOLD}; font-size: 15pt; font-weight: 700; }}
QLabel#pageTitle {{ font-size: 17pt; font-weight: 700; }}
QLabel#cardTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#help {{ color: {DIM}; font-size: 9pt; }}
QLabel#overline {{ color: {DIM}; font-size: 8.5pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#big {{ font-size: 21pt; font-weight: 700; }}
QLabel#statValue {{ font-size: 17pt; font-weight: 700; }}
QLabel#action {{ color: {BLUE}; font-weight: 600; }}
QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 7px 14px;
               font-weight: 600; }}
QPushButton:hover {{ background: {SURFACE_3}; }}
QPushButton:pressed {{ background: {BORDER_STRONG}; }}
QPushButton:disabled {{ color: {DIM}; background: {SURFACE}; border-color: {BORDER}; }}
QPushButton#primary {{ background: {GREEN}; color: #06140c; border: none; padding: 8px 18px; }}
QPushButton#primary:hover {{ background: #3ad889; }}
QPushButton#warn {{ background: {AMBER}; color: #1a1205; border: none; padding: 8px 16px; }}
QPushButton#warn:hover {{ background: #ffb83d; }}
QPushButton#danger {{ background: {RED}; color: #ffffff; border: none; padding: 8px 16px; }}
QPushButton#danger:hover {{ background: #ff6676; }}
QPushButton#primary:disabled, QPushButton#warn:disabled, QPushButton#danger:disabled {{
    background: {SURFACE_2}; color: {DIM}; }}
QPushButton#nav {{ text-align: left; padding: 10px 14px; border: none; border-radius: 9px; color: {MUTED};
                   background: transparent; font-weight: 600; }}
QPushButton#nav:hover:!checked {{ background: rgba(255, 255, 255, 0.03); color: {TEXT}; }}
QPushButton#nav:checked {{ background: transparent; color: {GOLD}; }}
QLineEdit, QSpinBox, QComboBox {{ background: {INPUT}; border: 1px solid {BORDER_STRONG}; border-radius: 7px;
                                 padding: 5px 8px; min-height: 22px; selection-background-color: #3a4378; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {GOLD}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: {DIM}; border-color: {BORDER}; }}
QComboBox QAbstractItemView {{ background: {SURFACE_2}; border: 1px solid {BORDER_STRONG}; outline: none;
                              selection-background-color: {SURFACE_3}; padding: 4px; }}
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #4a5480; border-radius: 4px; background: {INPUT}; }}
QCheckBox::indicator:hover {{ border-color: {GOLD}; }}
QCheckBox::indicator:checked {{ background: {GOLD}; border-color: {GOLD}; image: url("{CHECK_SVG}"); }}
QCheckBox::indicator:disabled {{ border-color: {BORDER}; }}
QListWidget {{ background: {INPUT}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; outline: none;
               padding: 4px; }}
QListWidget::item {{ padding: 4px 6px; border-radius: 6px; color: {TEXT}; }}
QListWidget::item:hover {{ background: {SURFACE_2}; }}
QListWidget::item:selected {{ background: rgba(245, 185, 66, 0.16); color: {TEXT}; }}
QListWidget::indicator {{ width: 15px; height: 15px; border: 1px solid #4a5480; border-radius: 4px;
                          background: {INPUT}; }}
QListWidget::indicator:checked {{ background: {GOLD}; border-color: {GOLD}; image: url("{CHECK_SVG}");
                                  }}
QTableWidget {{ background: transparent; border: none; gridline-color: transparent; outline: none;
                alternate-background-color: rgba(255, 255, 255, 0.018); }}
QTableWidget::item {{ padding: 0 8px; border-bottom: 1px solid {BORDER}; }}
QTableWidget::item:selected {{ background: rgba(91, 140, 255, 0.18); color: {TEXT}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER_STRONG};
                       padding: 8px; font-weight: 600; }}
QHeaderView::section:vertical {{ color: {DIM}; border-bottom: 1px solid {BORDER}; padding: 0 8px; }}
QTableCornerButton::section {{ background: transparent; border: none; }}
QProgressBar {{ background: {INPUT}; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; }}
QProgressBar::chunk {{ border-radius: 4px; background: {ELIXIR}; }}
QProgressBar[res="gold"]::chunk {{ background: {GOLD}; }}
QProgressBar[res="dark"]::chunk {{ background: {DARK}; }}
QProgressBar[full="true"]::chunk {{ background: {GREEN}; }}
QPlainTextEdit#log {{ background: {SIDEBAR}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px;
                      font-family: 'Cascadia Mono', Consolas; font-size: 9pt; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_STRONG}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width: 0; height: 0;
                                                                                          background: none; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; padding: 4px; }}
"""


# ----------------------------------------------------------------------------- small helpers
def _int(text, default=0):
    try:
        return int(str(text).replace(",", "").replace(" ", "").strip() or default)
    except ValueError:
        return default


def _fmt(n):
    return f"{n:,}" if n else ""


def short(n):
    """26939446 -> 26.9M, 58836 -> 58.8k."""
    if n is None:
        return "?"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _spinbox(lo, hi, value, suffix=""):
    sp = QSpinBox()
    sp.setRange(lo, hi)                                 # the range first: a value above 99 would be cut
    sp.setValue(int(value))
    sp.setSuffix(suffix)
    return sp


def _label(text="", name=None, wrap=False):
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def _icon_label(name, color=MUTED, size=18):
    lbl = QLabel()
    lbl.setPixmap(icons.pixmap(name, color, size))
    lbl.setFixedSize(size + 2, size + 2)
    return lbl


def _button(text, icon_name=None, name=None, color=TEXT, slot=None, tip=None):
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if icon_name:
        b.setIcon(icons.icon(icon_name, color, 16))
        b.setIconSize(QSize(16, 16))
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def _rgba(color, alpha):
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


class Glyph(QWidget):
    """A gold coin / elixir drop / dark elixir drop."""

    def __init__(self, res, size=18):
        super().__init__()
        self.res = res
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        icons.paint_resource(p, self.res, self.rect())
        p.end()


class ModeCombo(QComboBox):
    """What to run: a dropdown with each mode's icon and name (six segmented buttons did not fit one row).
    value() / set_value() / changed(str) like the segmented control it replaces."""
    changed = Signal(str)

    def __init__(self, modes):
        super().__init__()
        self.setIconSize(QSize(18, 18))
        self.setMinimumWidth(250)
        self.setMinimumHeight(36)
        self.setCursor(Qt.PointingHandCursor)
        for data, text, ic, colour in modes:
            self.addItem(icons.icon(ic, colour, 18), text, data)
        self.currentIndexChanged.connect(lambda _: self.changed.emit(self.value()))

    def value(self):
        return self.currentData()

    def set_value(self, mode):
        i = self.findData(mode)
        if i >= 0 and i != self.currentIndex():
            self.blockSignals(True)
            self.setCurrentIndex(i)
            self.blockSignals(False)


class Card(QFrame):
    """A rounded panel with an optional icon, title and subtitle; add content to card.body."""

    def __init__(self, title=None, subtitle=None, icon_name=None):
        super().__init__()
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 18)
        self.body.setSpacing(12)
        self.header = QHBoxLayout()
        self.header.setSpacing(10)
        if icon_name:
            self.header.addWidget(_icon_label(icon_name, GOLD, 18))
        if title:
            self.header.addWidget(_label(title, "cardTitle"))
        self.header.addStretch(1)
        if title or icon_name:
            self.body.addLayout(self.header)
        if subtitle:
            self.body.addWidget(_label(subtitle, "muted", wrap=True))


class StatCard(QFrame):
    """A counter; numbers count up to each new value (fmt turns the number into its text)."""

    def __init__(self, title, icon_name=None, res=None, color=TEXT, fmt=str):
        super().__init__()
        self.setObjectName("stat")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(Glyph(res, 16) if res else _icon_label(icon_name, MUTED, 16))
        top.addWidget(_label(title, "muted"))
        top.addStretch(1)
        lay.addLayout(top)
        self.value = _label("0", "statValue")
        self.value.setStyleSheet(f"color: {color};")
        lay.addWidget(self.value)
        self.counter = motion.CountUp(self.value, fmt)

    def set(self, text):
        self.value.setText(text)

    def count(self, n):
        self.counter.set(n)


class Chip(QLabel):
    """A coloured status label; its background lights up for a moment when the status changes."""

    def __init__(self):
        super().__init__()
        self.key = None
        self.flash = motion.Flash(self)

    def set(self, key, extra=""):
        text, colour = STATUS.get(key, (key, MUTED))
        self.setText(text + (f"  ·  {extra}" if extra else ""))
        if key != self.key:
            self.flash.set(colour, "border-radius: 10px; padding: 2px 10px; font-weight: 600; font-size: 9pt;",
                           animate=self.key is not None)
            self.key = key


class ResourceBar(QWidget):
    """Glyph, progress bar and "26.9M / 30.5M" for one resource."""

    def __init__(self, res, compact=False):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8 if compact else 0, 0, 8 if compact else 0, 0)
        lay.setSpacing(8)
        self.glyph = Glyph(res, 14 if compact else 18)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.setProperty("res", res)
        self.text = _label("", "muted")
        self.text.setMinimumWidth(150 if compact else 190)
        lay.addWidget(self.glyph)
        lay.addWidget(self.bar, 1)
        lay.addWidget(self.text)
        self.slide = QPropertyAnimation(self.bar, b"value", self)       # the bar glides to each new value
        self.slide.setDuration(700)
        self.slide.setEasingCurve(QEasingCurve.OutCubic)

    def set_res(self, res):
        self.glyph.res = res
        self.glyph.update()
        self.bar.setProperty("res", res)
        self.bar.style().unpolish(self.bar)
        self.bar.style().polish(self.bar)

    def set(self, value, full_at):
        frac = min(1.0, value / full_at) if value is not None and full_at else 0.0
        target = int(frac * 1000)
        heading = self.slide.endValue() if self.slide.state() == QAbstractAnimation.Running else self.bar.value()
        if target != heading:
            self.slide.stop()
            self.slide.setStartValue(self.bar.value())
            self.slide.setEndValue(target)
            self.slide.start()
        is_full = bool(full_at and value is not None and value >= full_at)
        if self.bar.property("full") != is_full:
            self.bar.setProperty("full", is_full)
            self.bar.style().unpolish(self.bar)
            self.bar.style().polish(self.bar)
        if value is None:
            self.text.setText(f"- / {short(full_at)}" if full_at else "-")
        else:
            self.text.setText(f"{short(value)} / {short(full_at)}  ({frac * 100:.0f}%)" if full_at else short(value))


class LogBridge(QObject, logging.Handler):
    """Log records -> the window (a Qt signal, so it is safe from the bot thread)."""
    line = Signal(str, str)

    def __init__(self):
        QObject.__init__(self)
        logging.Handler.__init__(self, logging.DEBUG)      # the Log page can show every step
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record):
        try:
            self.line.emit(record.levelname, self.format(record))
        except Exception:  # noqa: BLE001 - never break the bot because of the window
            pass


# ----------------------------------------------------------------------------- the window
class Window(QMainWindow):
    finished = Signal(str)

    PAGES = [("dashboard", "Dashboard", "Dashboard", "What the bot is doing right now"),
             ("users", "Accounts", "Accounts", "Your accounts, in the same order as the game's Supercell ID list"),
             ("sliders", "Loot settings", "Loot settings", "When an account is full, which base to attack, the battle"),
             ("layers", "Storage && loot", "Full storage and minimum loot", "Per Town Hall"),
             ("terminal", "Log", "Log", "Everything the bot did, as it happened")]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("COC Bot")
        self.setWindowIcon(icons.app_icon())
        self.resize(1440, 900)                          # the size after leaving maximized
        self.setMinimumSize(1120, 700)
        self.settings = config.load_settings()
        self.accounts = config.load_accounts() if os.path.exists(config.ACCOUNTS_PATH) else []
        self.bot = None
        self.thread = None
        self.started_at = None
        self.ended_at = None
        self.dirty = False
        self.loading = True
        self.lines = collections.deque(maxlen=6000)    # (level, text) for the log page's filter

        root = QWidget(objectName="root")
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._sidebar())
        main = QVBoxLayout()
        main.setContentsMargins(26, 20, 26, 22)
        main.setSpacing(16)
        main.addLayout(self._topbar())
        self.stack = motion.AnimatedStack()
        self.stack.addWidget(self._dashboard())
        self.stack.addWidget(self._lockable(self._accounts_page()))
        self.stack.addWidget(self._lockable(self._settings_page()))
        self.stack.addWidget(self._lockable(self._storage_page()))
        self.stack.addWidget(self._log_page())
        main.addWidget(self.stack, 1)
        outer.addLayout(main, 1)
        self.setCentralWidget(root)
        self.toasts = motion.Toasts(root, {"info": BLUE, "success": GREEN, "warning": AMBER, "error": RED},
                                    lambda kind, colour: icons.pixmap(TOAST_ICON.get(kind, "info"), colour, 18),
                                    SURFACE_2, BORDER_STRONG, TEXT)
        self._last_error_toast = 0.0

        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save)
        self.finished.connect(self._on_finished)
        self.timer = QTimer(self, interval=1000, timeout=self._refresh)
        self.timer.start()
        self.loading = False
        self._go(0, animate=False)
        self._set_running(False)
        self._set_dirty(False)
        self._show_mode()
        motion.fade_in(self.dash_cards)                 # the dashboard's cards appear one after another

    # --- frame ---------------------------------------------------------------------------------------
    def _sidebar(self):
        side = QFrame(objectName="sidebar")
        side.setFixedWidth(232)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(16, 20, 16, 18)
        lay.setSpacing(4)
        logo = QHBoxLayout()
        logo.setSpacing(10)
        mark = QLabel()
        mark.setPixmap(icons.app_icon().pixmap(36, 36))
        logo.addWidget(mark)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(_label("COC Bot", "logo"))
        self.side_mode = _label("", "help")
        names.addWidget(self.side_mode)
        logo.addLayout(names)
        logo.addStretch(1)
        lay.addLayout(logo)
        lay.addSpacing(22)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.nav_rail = motion.NavRail()                # the highlight slides to the chosen page
        self.nav_buttons = []
        for i, (icon_name, text, _, _) in enumerate(self.PAGES):
            b = QPushButton(text, objectName="nav", checkable=True)
            b.setIconSize(QSize(18, 18))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self._go(i))
            self.nav.addButton(b, i)
            self.nav_buttons.append((b, icon_name))
            self.nav_rail.add(b)
        lay.addWidget(self.nav_rail)
        lay.addStretch(1)
        status = QFrame(objectName="stat")
        sl = QVBoxLayout(status)
        sl.setContentsMargins(14, 12, 14, 12)
        sl.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.status_dot = motion.PulseDot(18)
        self.status_text = _label("Stopped", "cardTitle")
        row.addWidget(self.status_dot)
        row.addWidget(self.status_text)
        row.addStretch(1)
        sl.addLayout(row)
        self.status_sub = _label("", "help", wrap=True)
        sl.addWidget(self.status_sub)
        lay.addWidget(status)
        lay.addSpacing(10)
        keys = QHBoxLayout()
        keys.setSpacing(6)
        keys.addWidget(_icon_label("keyboard", DIM, 16))
        keys.addWidget(_label("F9 pause / continue    F10 stop", "help"))
        keys.addStretch(1)
        lay.addLayout(keys)
        return side

    def _topbar(self):
        row = QHBoxLayout()
        row.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.page_title = _label("", "pageTitle")
        self.page_sub = _label("", "muted")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_sub)
        row.addLayout(titles)
        row.addStretch(1)
        self.save_state = _label("", "help")
        row.addWidget(self.save_state)
        self.save_btn = _button("Save", "save", slot=lambda: self.save(), tip="Save settings and accounts (Ctrl+S)")
        self.check_btn = _button("Check setup", "scan", slot=self.check,
                                 tip="Start BlueStacks and the game and read the resources - no attack")
        self.start_btn = _button("Start", "play", "primary", "#06140c", self.start,
                                 "Run the mode chosen on the Dashboard, from its start account")
        self.pause_btn = _button("Pause", "pause", "warn", "#1a1205", control.toggle_pause, "Pause / continue (F9)")
        self.stop_btn = _button("Stop", "stop", "danger", "#ffffff", self.stop, "Stop (F10)")
        for b in (self.save_btn, self.check_btn, self.start_btn, self.pause_btn, self.stop_btn):
            row.addWidget(b)
        self.glows = [motion.Glow(self.start_btn, GREEN, breathe=True), motion.Glow(self.pause_btn, AMBER),
                      motion.Glow(self.stop_btn, RED)]
        return row

    def _lockable(self, page):
        """A settings page with a notice on top that shows while the bot runs (the page is locked then)."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        banner = QFrame(objectName="banner")
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(14, 10, 14, 10)
        bl.addWidget(_icon_label("shield", AMBER, 16))
        bl.addWidget(_label("Locked while the bot runs: these settings were read at Start. Stop the bot to change "
                            "them.", "muted", wrap=True), 1)
        banner.hide()
        lay.addWidget(banner)
        lay.addWidget(page, 1)
        w.banner, w.page = banner, page
        return w

    def _go(self, i, animate=True):
        self.stack.show_page(i, animate)
        self.nav_rail.select(i, animate)
        for j, (b, icon_name) in enumerate(self.nav_buttons):
            b.setChecked(j == i)
            b.setIcon(icons.icon(icon_name, GOLD if j == i else MUTED, 18))
        _, _, title, sub = self.PAGES[i]
        self.page_title.setText(title)
        self.page_sub.setText(sub)

    # --- dashboard -----------------------------------------------------------------------------------
    def _dashboard(self):
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)

        # what to run and from which account (follows the run, so the next run goes on from where it stopped)
        run = Card()
        run.body.setContentsMargins(18, 12, 18, 12)
        rl = QHBoxLayout()
        rl.setSpacing(14)
        self.mode = ModeCombo(MODES)
        self.mode.setToolTip("What the bot does when you press Start")
        self.mode.set_value(self.settings.get("mode", "loot"))
        self.mode.changed.connect(self._mode_changed)
        what = QVBoxLayout()
        what.setSpacing(5)
        what.addWidget(_label("WHAT TO RUN", "overline"))
        what.addWidget(self.mode)
        self.mode.setMinimumWidth(300)
        self.mode.setMaximumWidth(340)
        what.addStretch(1)
        self.mode_help = _label("", "help", wrap=True)   # under both pickers, the card's whole width
        rl.addLayout(what)
        rl.addSpacing(18)
        start = QVBoxLayout()
        start.setSpacing(5)
        title = QHBoxLayout()
        title.setSpacing(6)
        title.addWidget(_icon_label("flag", GOLD, 14))
        title.addWidget(_label("START FROM ACCOUNT", "overline"))
        title.addStretch(1)
        start.addLayout(title)
        self.start_combo = QComboBox()
        self.start_combo.setMinimumWidth(280)
        self.start_combo.setToolTip("The account the run starts with. It follows the run (it shows the account the "
                                    "bot is on), so after a stop the next run goes on from there; after a whole "
                                    "round it is back at the first account.")
        self.start_combo.currentIndexChanged.connect(self._start_changed)
        start.addWidget(self.start_combo)
        self.start_hint = _label("Moves along as the bot changes account", "help")
        start.addWidget(self.start_hint)
        rl.addLayout(start)
        rl.addStretch(1)
        self.raid_pill = _label("", "pill")
        rl.addWidget(self.raid_pill, 0, Qt.AlignVCenter)
        run.body.addLayout(rl)
        run.body.addWidget(self.mode_help)
        grid.addWidget(run, 0, 0, 1, 2)
        self._fill_start()

        now = Card()
        now.body.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(_label("NOW", "overline"))
        head.addStretch(1)
        now.body.addLayout(head)
        self.shimmer = motion.Shimmer(BLUE)             # a light runs along it while the bot works
        now.body.addWidget(self.shimmer)
        self.now_account = _label("Not running", "big")
        now.body.addWidget(self.now_account)
        self.now_meta = _label("", "muted")
        now.body.addWidget(self.now_meta)
        act = QHBoxLayout()
        act.setSpacing(8)
        self.now_icon = _icon_label("bolt", BLUE, 16)
        act.addWidget(self.now_icon)
        self.now_action = _label("", "action")
        self.now_action_fade = motion.FadeText(self.now_action, BLUE)
        act.addWidget(self.now_action)
        act.addStretch(1)
        now.body.addLayout(act)
        now.body.addSpacing(6)
        self.now_res_title = _label("", "help")
        now.body.addWidget(self.now_res_title)
        self.now_bar = ResourceBar(self._watch_res())
        now.body.addWidget(self.now_bar)
        now.body.addSpacing(4)
        self.last_row = QWidget()
        last = QHBoxLayout(self.last_row)
        last.setContentsMargins(0, 0, 0, 0)
        last.setSpacing(8)
        last.addWidget(_label("Last base", "help"))
        self.last_vals = {}
        for r in RESOURCES:
            last.addSpacing(8)
            last.addWidget(Glyph(r, 14))
            self.last_vals[r] = _label("-", "muted")
            last.addWidget(self.last_vals[r])
        last.addStretch(1)
        now.body.addWidget(self.last_row)
        now.body.addStretch(1)
        grid.addWidget(now, 1, 0)

        stats = Card("This run", icon_name="target")
        sg = QGridLayout()
        sg.setSpacing(10)
        self.stat_cards = {
            "attacks": StatCard("Attacks", "swords"),
            "raids": StatCard("Raid attacks", "castle", color=ORANGE),
            "searches": StatCard("Searches", "search"),
            "time": StatCard("Run time", "clock"),
            "gold": StatCard("Gold gained", res="gold", color=GOLD, fmt=lambda n: f"+{short(n)}" if n else "0"),
            "elixir": StatCard("Elixir gained", res="elixir", color=ELIXIR,
                               fmt=lambda n: f"+{short(n)}" if n else "0"),
            "dark": StatCard("Dark gained", res="dark", color=DARK, fmt=lambda n: f"+{short(n)}" if n else "0"),
            "done": StatCard("Accounts done", "check-circle", color=GREEN),
            "requests": StatCard("Requests sent", "flag", color=BLUE),
            "donated": StatCard("Units donated", "users", color=ELIXIR),
            "upgrades": StatCard("Upgrades started", "arrow-up", color=GOLD),
            "walls": StatCard("Walls upgraded", "shield", color=AMBER),
        }
        for i, card in enumerate(self.stat_cards.values()):    # all placed once; _layout_stats shows the mode's
            sg.addWidget(card, i // 4, i % 4)
        self.stat_grid = sg
        stats.body.addLayout(sg)
        stats.body.addStretch(1)
        grid.addWidget(stats, 1, 1)

        accs = Card("Accounts this run", icon_name="users")
        self.dash_count = _label("", "help")
        accs.header.addWidget(self.dash_count)
        self.dash_table = QTableWidget(0, 5)
        self.dash_table.setHorizontalHeaderLabels(["#", "Account", "TH", "", "Status"])
        h = self.dash_table.horizontalHeader()
        for c, mode in enumerate((QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
                                  QHeaderView.ResizeToContents, QHeaderView.Stretch, QHeaderView.Fixed)):
            h.setSectionResizeMode(c, mode)
        self.dash_table.setColumnWidth(4, 200)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.dash_table.verticalHeader().hide()
        self.dash_table.verticalHeader().setDefaultSectionSize(38)
        self.dash_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.dash_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.dash_table.setFocusPolicy(Qt.NoFocus)
        self.dash_table.setShowGrid(False)
        accs.body.addWidget(self.dash_table, 1)
        grid.addWidget(accs, 2, 0)

        recent = Card("Recent activity", icon_name="list")
        recent.header.addWidget(_button("Full log", "terminal", slot=lambda: self._go(4)))
        self.recent = QPlainTextEdit(readOnly=True, objectName="log")
        self.recent.setMaximumBlockCount(400)
        recent.body.addWidget(self.recent, 1)
        grid.addWidget(recent, 2, 1)

        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.setRowStretch(2, 1)
        self.dash_cards = [run, now, stats, accs, recent]
        self._fill_dashboard_accounts()
        return w

    # the run bar: mode and start account ----------------------------------------------------------------
    def _mode_changed(self, mode):
        """A run control, not a setting: saved at once (other unsaved edits stay unsaved)."""
        self.settings["mode"] = mode
        config.save_settings(self.settings)
        self._fill_dashboard_accounts()
        self._show_mode()
        self.note(f"Mode: {runner.MODES.get(mode, mode)}")

    def _show_mode(self):
        mode = self.mode.value()
        self.mode_help.setText(MODE_HELP.get(mode, ""))
        self.side_mode.setText(runner.MODES.get(mode, mode))
        colour = next((c for d, _, _, c in MODES if d == mode), BLUE)
        self.shimmer.set_color(colour)
        donating = mode in DONATE_MODES
        self.start_combo.setEnabled(getattr(self, "thread", None) is None and not donating)
        hints = {"loot_donate": "Loot + donate always starts on the main account",
                 "donate_only": "Donate + loot (PC 1) always runs on the main account",
                 "request_only": "Request only (PC 2) cycles through the requesting accounts"}
        self.start_hint.setText(hints.get(mode, "Moves along as the bot changes account"))
        self.dash_table.setColumnHidden(3, mode in ("raid", "request_only"))
        self._layout_stats()

    STATS = ("attacks", "raids", "searches", "time", "gold", "elixir", "dark", "done")
    STATS_BY_MODE = {"loot_donate": ("attacks", "requests", "donated", "time", "gold", "elixir", "dark", "searches"),
                     "donate_only": ("attacks", "donated", "searches", "time", "gold", "elixir", "dark", "done"),
                     "request_only": ("requests", "time"),
                     "loot_upgrade": ("attacks", "upgrades", "searches", "time", "gold", "elixir", "dark", "done"),
                     "loot_walls": ("attacks", "walls", "searches", "time", "gold", "elixir", "dark", "done")}

    def _layout_stats(self):
        """The mode's eight counters, in its order."""
        order = self.STATS_BY_MODE.get(self.mode.value(), self.STATS)
        for card in self.stat_cards.values():
            self.stat_grid.removeWidget(card)
            card.hide()
        for i, key in enumerate(order):
            self.stat_grid.addWidget(self.stat_cards[key], i // 4, i % 4)
            self.stat_cards[key].show()

    def _fill_start(self):
        """The ticked accounts for "Start from account" (#position, name, Town Hall)."""
        c = self.start_combo
        c.blockSignals(True)
        c.clear()
        for i, a in enumerate(self.accounts, 1):
            if a.get("enabled", True):
                th = a.get("th")
                c.addItem(f"#{i}  {a['name']}{f'  ·  TH {th}' if th else ''}", i)
        if c.count():
            pos = max(1, int(self.settings.get("start_from", 1) or 1))
            idx = c.findData(pos)
            if idx < 0:                                   # that account is unticked now: the next one after it
                later = [j for j in range(c.count()) if c.itemData(j) > pos]
                idx = later[0] if later else 0
            c.setCurrentIndex(idx)
        c.blockSignals(False)

    def _start_changed(self, *_):
        pos = self.start_combo.currentData()
        if pos and self.thread is None:
            self.settings["start_from"] = int(pos)
            config.save_settings(self.settings)

    def _follow_start(self, pos):
        """The run moved on to account #pos (back to #1 after a whole round): shown and saved."""
        pos = int(pos or 1)
        if pos != int(self.settings.get("start_from", 1) or 1):
            self.settings["start_from"] = pos
            config.save_settings(self.settings)
            self._fill_start()

    def _watch_res(self):
        w = self.settings["loot"]["watch"]
        return next((r for r in RESOURCES if w.get(r)), "elixir")

    def _dashboard_accounts(self):
        """[(pos, acc)] shown in the Dashboard table for the current mode."""
        mode = self.mode.value() if hasattr(self, "mode") else self.settings.get("mode", "loot")
        if mode not in DONATE_MODES:
            return [(i, a) for i, a in enumerate(self.accounts, 1) if a.get("enabled", True)]
        d = self.settings.get("donate", {})
        main_pos = d.get("main", 1)
        main_pos = 1 if main_pos is None else int(main_pos)
        top = int(d.get("request_top", 30) or 0) or len(self.accounts)
        if mode == "donate_only":
            return [(main_pos, self.accounts[main_pos - 1])] if 1 <= main_pos <= len(self.accounts) else []
        if mode == "request_only":
            return [(i, a) for i, a in enumerate(self.accounts[:top], 1) if i != main_pos]
        partner_pos = d.get("partner", 2)
        partner_pos = 0 if partner_pos is None else int(partner_pos)
        seen, out = set(), []
        for pos in [main_pos, partner_pos] + list(range(1, min(top, len(self.accounts)) + 1)):
            if 1 <= pos <= len(self.accounts) and pos not in seen:
                seen.add(pos)
                out.append((pos, self.accounts[pos - 1]))
        return out

    def _fill_dashboard_accounts(self):
        """One row per active account (rebuilt when the accounts, mode, or settings change, or a run starts)."""
        res = self._watch_res()
        mode = self.mode.value() if hasattr(self, "mode") else self.settings.get("mode", "loot")
        t = self.dash_table
        t.setRowCount(0)
        t.horizontalHeaderItem(3).setText(f"{RES_NAME[res]} / full storage")
        t.setColumnHidden(3, mode in ("raid", "request_only"))
        self.dash_rows = []
        shown = self._dashboard_accounts()
        for pos, acc in shown:
            r = t.rowCount()
            t.insertRow(r)
            num = QTableWidgetItem(str(pos))
            num.setForeground(QColor(DIM))
            t.setItem(r, 0, num)
            name = QTableWidgetItem(acc["name"])
            t.setItem(r, 1, name)
            th = QTableWidgetItem(str(acc.get("th") or "?"))
            th.setForeground(QColor(MUTED))
            t.setItem(r, 2, th)
            bar = ResourceBar(res, compact=True)
            bar.set(None, config.full_at(self.settings, acc, res))
            t.setCellWidget(r, 3, bar)
            chip = Chip()
            chip.set("waiting")
            cell = QWidget()
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(8, 0, 8, 0)
            cl.addWidget(chip, 0, Qt.AlignVCenter)
            cl.addStretch(1)
            t.setCellWidget(r, 4, cell)
            self.dash_rows.append((acc, bar, chip, name))
        self.dash_count.setText(f"{len(shown)} account(s)" if mode in DONATE_MODES else f"{len(shown)} ticked")
        self.dash_current = None

    def _mark_current(self, name):
        """The account the bot is on: its name in gold and bold, scrolled into view."""
        if name == self.dash_current:
            return
        self.dash_current = name
        for a, _, _, item in self.dash_rows:
            on = a["name"] == name
            f = item.font()
            f.setBold(on)
            item.setFont(f)
            item.setForeground(QColor(GOLD if on else TEXT))
            if on:
                self.dash_table.scrollToItem(item)

    # --- accounts ------------------------------------------------------------------------------------
    def _accounts_page(self):
        card = Card()
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.acc_search = QLineEdit(placeholderText="Search accounts")
        self.acc_search.addAction(icons.icon("search", DIM, 16), QLineEdit.LeadingPosition)
        self.acc_search.setFixedWidth(240)
        self.acc_search.textChanged.connect(self._filter_accounts)
        bar.addWidget(self.acc_search)
        self.acc_count = _label("", "muted")
        bar.addSpacing(6)
        bar.addWidget(self.acc_count)
        bar.addStretch(1)
        bar.addWidget(_button("Add", "plus", slot=self._new_account))
        bar.addWidget(_button("Remove", "trash", slot=self._remove_account))
        bar.addWidget(_button("", "arrow-up", slot=lambda: self._move_account(-1), tip="Move up"))
        bar.addWidget(_button("", "arrow-down", slot=lambda: self._move_account(1), tip="Move down"))
        bar.addWidget(_button("Tick all", "check", slot=lambda: self._tick_all(True)))
        bar.addWidget(_button("Untick all", slot=lambda: self._tick_all(False)))
        card.body.addLayout(bar)
        card.body.addWidget(_label("Ticked accounts are looted from top to bottom. The Town Hall picks the full storage "
                                   "and the minimum loot (Storage & loot page). 'Own full elixir' overrides the full "
                                   "storage for that account only.", "help", wrap=True))
        t = self.acc_table = QTableWidget(0, 4)
        t.setHorizontalHeaderLabels(["Loot", "Account name", "Town Hall", "Own full elixir"])
        h = t.horizontalHeader()
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        t.setColumnWidth(0, 64)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.Fixed)
        t.setColumnWidth(2, 130)
        h.setSectionResizeMode(3, QHeaderView.Fixed)
        t.setColumnWidth(3, 190)
        t.verticalHeader().setDefaultSectionSize(40)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setShowGrid(False)
        t.itemChanged.connect(self._account_item_changed)
        for acc in self.accounts:
            self._add_account_row(acc)
        card.body.addWidget(t, 1)
        self._count_accounts()
        return card

    def _add_account_row(self, acc, edit=False):
        t = self.acc_table
        r = t.rowCount()
        t.blockSignals(True)
        t.insertRow(r)
        on = QCheckBox()
        on.setChecked(bool(acc.get("enabled", True)))
        on.toggled.connect(lambda _: (self._count_accounts(), self._set_dirty(True)))
        cell = QWidget()
        cl = QHBoxLayout(cell)
        cl.setContentsMargins(14, 0, 0, 0)
        cl.addWidget(on)
        t.setCellWidget(r, 0, cell)
        name = QTableWidgetItem(acc.get("name", ""))
        name.setData(Qt.UserRole, acc)                  # keeps any other keys of the account
        t.setItem(r, 1, name)
        th = QComboBox()
        for n in range(19, 0, -1):
            th.addItem(f"TH {n}", n)
        th.setCurrentIndex(max(0, th.findData(int(acc.get("th") or 15))))
        th.currentIndexChanged.connect(lambda _: self._set_dirty(True))
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(4, 3, 10, 3)
        hl.addWidget(th)
        t.setCellWidget(r, 2, holder)
        own = QTableWidgetItem(_fmt((acc.get("full_at") or {}).get("elixir", 0)))
        own.setToolTip("Leave empty to use the Town Hall's full storage")
        t.setItem(r, 3, own)
        t.blockSignals(False)
        if edit:
            t.setCurrentCell(r, 1)
            t.editItem(name)

    def _row_values(self, r):
        t = self.acc_table
        acc = dict(t.item(r, 1).data(Qt.UserRole) or {})
        acc["name"] = t.item(r, 1).text().strip()
        acc["th"] = t.cellWidget(r, 2).findChild(QComboBox).currentData()
        acc["enabled"] = t.cellWidget(r, 0).findChild(QCheckBox).isChecked()
        own = _int(t.item(r, 3).text() if t.item(r, 3) else "")
        full = dict(acc.get("full_at") or {})
        if own:
            full["elixir"] = own
        else:
            full.pop("elixir", None)
        if any(full.values()):
            acc["full_at"] = full
        else:
            acc.pop("full_at", None)
        return acc

    def _accounts_from_table(self):
        return [a for a in (self._row_values(r) for r in range(self.acc_table.rowCount())) if a["name"]]

    def _account_item_changed(self, item):
        if item.column() == 3:                          # show the number with thousands separators
            n = _int(item.text())
            self.acc_table.blockSignals(True)
            item.setText(_fmt(n))
            self.acc_table.blockSignals(False)
        self._set_dirty(True)

    def _new_account(self):
        self.acc_search.clear()
        self._add_account_row({"name": "", "th": 15, "enabled": True}, edit=True)
        self._count_accounts()
        self._set_dirty(True)

    def _remove_account(self):
        rows = sorted({i.row() for i in self.acc_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.acc_table.removeRow(r)
        if rows:
            self._count_accounts()
            self._set_dirty(True)

    def _move_account(self, step):
        r = self.acc_table.currentRow()
        if r < 0 or not 0 <= r + step < self.acc_table.rowCount():
            return
        accs = [self._row_values(i) for i in range(self.acc_table.rowCount())]
        accs[r], accs[r + step] = accs[r + step], accs[r]
        self.acc_table.setRowCount(0)
        for a in accs:
            self._add_account_row(a)
        self.acc_table.setCurrentCell(r + step, 1)
        self._filter_accounts(self.acc_search.text())
        self._set_dirty(True)

    def _tick_all(self, on):
        for r in range(self.acc_table.rowCount()):
            if not self.acc_table.isRowHidden(r):
                self.acc_table.cellWidget(r, 0).findChild(QCheckBox).setChecked(on)

    def _filter_accounts(self, text):
        text = text.strip().lower()
        for r in range(self.acc_table.rowCount()):
            self.acc_table.setRowHidden(r, bool(text) and text not in self.acc_table.item(r, 1).text().lower())

    def _count_accounts(self):
        n = self.acc_table.rowCount()
        on = sum(self.acc_table.cellWidget(r, 0).findChild(QCheckBox).isChecked() for r in range(n))
        self.acc_count.setText(f"{on} of {n} ticked")

    # --- loot settings -------------------------------------------------------------------------------
    def _settings_page(self):
        s, lo = self.settings, self.settings["loot"]
        self.f = {}
        inner = QWidget()
        cols = QHBoxLayout(inner)
        cols.setContentsMargins(0, 0, 6, 0)
        cols.setSpacing(16)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.setSpacing(16)
        right.setSpacing(16)
        cols.addLayout(left, 1)
        cols.addLayout(right, 1)

        def section(title, icon_name, column):
            card = Card(title, icon_name=icon_name)
            grid = QGridLayout()
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(14)
            grid.setColumnStretch(0, 1)
            card.body.addLayout(grid)
            column.addWidget(card)
            return grid

        def row(grid, title, help_text, widget):
            text = QVBoxLayout()
            text.setSpacing(2)
            text.addWidget(_label(title))
            if help_text:
                text.addWidget(_label(help_text, "help", wrap=True))
            r = grid.rowCount()
            grid.addLayout(text, r, 0)
            grid.addWidget(widget, r, 1, Qt.AlignRight | Qt.AlignVCenter)

        def spin(key, value, lo_, hi, suffix=""):
            sp = _spinbox(lo_, hi, value, suffix)
            sp.setFixedWidth(150)
            sp.valueChanged.connect(lambda _: self._set_dirty(True))
            self.f[key] = sp
            return sp

        def combo(key, items, value, width=230):
            c = QComboBox()
            for text, data in items:
                c.addItem(text, data)
            c.setCurrentIndex(max(0, c.findData(value)))
            c.setFixedWidth(width)
            c.currentIndexChanged.connect(lambda _: self._set_dirty(True))
            self.f[key] = c
            return c

        def check(key, value, text=""):
            c = QCheckBox(text)
            c.setChecked(bool(value))
            c.toggled.connect(lambda _: self._set_dirty(True))
            self.f[key] = c
            return c

        def edit(key, value, placeholder):
            e = QLineEdit(value, placeholderText=placeholder)
            e.setFixedWidth(230)
            e.textEdited.connect(lambda _: self._set_dirty(True))
            self.f[key] = e
            return e

        g = section("Run", "play", left)
        row(g, "Rounds over all accounts", "0 = keep going round the accounts until you stop it. The mode and the "
                                           "start account are on the Dashboard",
            spin("repeat_rounds", s.get("repeat_rounds", 1), 0, 999))
        row(g, "When every account is done", "Not after Stop. Shut down: Clash of Clans and BlueStacks close, "
                                              "the PC shuts down 1 minute later and the bot closes itself "
                                              "(to keep the PC on: Win+R, shutdown /a)",
            combo("when_done", [(text, key) for key, text in runner.AFTER_RUN.items()], s.get("when_done", "nothing"),
                  width=260))
        row(g, "Another device plays this account", "Minutes to wait before Reload, so you can play on your phone "
                                                    "(0 = Reload at once)",
            spin("another_device_wait", int(s.get("another_device_wait", 0) or 0), 0, 120, " min"))

        g = section("When is an account full?", "layers", left)
        res_box = QWidget()
        rb = QHBoxLayout(res_box)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.setSpacing(14)
        for r in RESOURCES:
            item = QHBoxLayout()
            item.setSpacing(6)
            item.addWidget(check(f"watch_{r}", lo["watch"].get(r)))
            item.addWidget(Glyph(r, 16))
            item.addWidget(_label(RES_NAME[r].split()[0]))
            rb.addLayout(item)
        row(g, "Resources to fill", "The full storage per Town Hall is on the Storage & loot page", res_box)
        row(g, "Full when", None, combo("full_rule", [("any of them is full", "any"), ("all of them are full", "all")],
                                         lo["full_rule"]))
        row(g, "Storages stopped growing", "Counts as full after this many attacks without loot",
            spin("stuck_attacks", lo["stuck_attacks"], 1, 20, " attacks"))
        row(g, "Max attacks per account", "0 = no limit", spin("max_attacks_per_account",
                                                               lo["max_attacks_per_account"], 0, 999))

        g = section("Choosing a base", "search", left)
        row(g, "Attack a base when", "The minimum loot per Town Hall is on the Storage & loot page",
            combo("min_loot_rule", [("any resource has the minimum", "any"), ("all have the minimum", "all")],
                  lo["min_loot_rule"]))
        row(g, "Max searches per attack", "Next is pressed at most this often, then it starts again",
            spin("max_searches", lo["max_searches"], 1, 1000))

        d = s.get("donate", {})

        def accounts_combo(key):
            c = QComboBox()
            c.setFixedWidth(230)
            c.currentIndexChanged.connect(lambda _: self._set_dirty(True))
            self.f[key] = c
            return c

        g = section("Loot + donate", "users", left)
        g.addWidget(_label("1 PC (Loot + donate): the main account donates when its elixir >= threshold while "
                           "partner and top accounts request; below that it loots and the partner loots too. "
                           "2 PCs: run 'Donate + loot (PC 1)' on the donor PC (only uses Main account) and "
                           "'Request only (PC 2)' on the requester PC (skips Main account if set, or set Main "
                           "account to 'None (other PC)' if PC 2 only lists requesting accounts).", "help", wrap=True),
                    g.rowCount(), 0, 1, 2)
        row(g, "Main account", "Donates, and loots when its elixir runs low (PC 1)", accounts_combo("donate_main"))
        row(g, "Partner account", "1 PC mode only: loots with the main account, and requests first",
            accounts_combo("donate_partner"))
        row(g, "Request troops from the top", "30 = the main account and the 29 accounts below it in the list "
                                                "(ticks do not matter here)",
            spin("donate_request_top", int(d.get("request_top", 30) or 30), 1, 500, " accounts"))
        need = spin("donate_need", min(int(d.get("need", 4000000) or 0), 100_000_000), 0, 100_000_000)
        need.setSingleStep(100_000)
        need.setGroupSeparatorShown(True)
        row(g, "Elixir a round needs", "40,00,000 = 40 lakh. Below this the main account loots", need)
        row(g, "Check requests every (PC 1)", "2-PC Donor mode: wait between clan chat checks when nothing was donated",
            spin("donate_poll_seconds", int(d.get("poll_seconds", 15) or 15), 3, 300, " s"))
        row(g, "Empty the Clan Castle first", "Before each request, so the castle has room",
            check("donate_empty_cc", d.get("empty_cc", True)))
        row(g, "Donate only to my accounts", "Off: to every open request in the clan chat",
            check("donate_only_mine", d.get("only_mine", False)))
        self._fill_donate()
        left.addStretch(1)

        g = section("Battle", "swords", right)
        row(g, "Attack plan", "From config/attack_plans.json",
            combo("attack_plan", [(p, p) for p in attack.load_plans()], lo["attack_plan"]))
        row(g, "End the battle after", "The longest a battle may last",
            spin("battle_seconds", lo["battle_seconds"], 20, 180, " s"))
        row(g, "End sooner when no loot comes in for", "Faster attacks; 0 = always wait the full time",
            spin("end_when_loot_stops", lo.get("end_when_loot_stops", 15), 0, 120, " s"))
        row(g, "Smart deploy", "Drop troops on a ring just outside the base's red area",
            check("smart_deploy", lo["smart_deploy"]))
        row(g, "Count troops", "Read each card's count and check that every tap deployed a unit",
            check("count_troops", lo["count_troops"]))
        row(g, "Zoom out before searching", None, check("zoom_out", lo["zoom_out"]))

        g = section("Army", "shield", right)
        g.addWidget(_label("Before the first attack on each account: army screen > the Saved Recipes tab > Use on "
                           "the top recipe. The game asks to confirm only when the Clan Castle has troops (then "
                           "Okay). Put your looting army first in each account's Saved Recipes.", "help", wrap=True),
                    g.rowCount(), 0, 1, 2)

        wl = s.get("walls", {})
        g = section("Loot + walls", "shield", right)
        g.addWidget(_label("Each account stays until its walls are done: the gold and elixir above what you keep "
                           "go into walls, it loots until full, walls again, and so on. It moves on when full "
                           "storages upgrade no wall (all done, waiting for a builder, or one wall costs more) or "
                           "looting stops. Cheapest walls first, many at once with Upgrade More; gold pays for every "
                           "level, elixir for the higher ones. Okay only when the game asks exactly that amount.",
                           "help", wrap=True), g.rowCount(), 0, 1, 2)
        wpay = QWidget()
        wp = QHBoxLayout(wpay)
        wp.setContentsMargins(0, 0, 0, 0)
        wp.setSpacing(14)
        for r in ("gold", "elixir"):
            item = QHBoxLayout()
            item.setSpacing(6)
            item.addWidget(check(f"walls_{r}", wl.get("spend", {}).get(r, True)))
            item.addWidget(Glyph(r, 16))
            item.addWidget(_label(RES_NAME[r].split()[0]))
            wp.addLayout(item)
        row(g, "Pay walls with", None, wpay)
        for r in ("gold", "elixir"):
            keep_w = spin(f"walls_keep_{r}", int(wl.get("keep", {}).get(r, 500000) or 0), 0, 50_000_000)
            keep_w.setSingleStep(100_000)
            keep_w.setGroupSeparatorShown(True)
            row(g, f"Always keep {r}", "Searching for bases costs gold" if r == "gold" else None, keep_w)

        u = s.get("upgrade", {})
        g = section("Loot + upgrade", "arrow-up", right)
        g.addWidget(_label("Before and after looting, each account opens the Build panel and starts upgrades from "
                           "the list below that it can pay, while a builder is free. Never with gems: the "
                           "Goblin Builder and \"Free a Builder\" are never used; when the game says every builder "
                           "is busy, the account is looked at again when its first upgrade is done.", "help",
                           wrap=True), g.rowCount(), 0, 1, 2)
        pay = QWidget()
        pl = QHBoxLayout(pay)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(14)
        for r in RESOURCES:
            item = QHBoxLayout()
            item.setSpacing(6)
            item.addWidget(check(f"spend_{r}", u.get("spend", {}).get(r, True)))
            item.addWidget(Glyph(r, 16))
            item.addWidget(_label(RES_NAME[r].split()[0]))
            pl.addLayout(item)
        row(g, "Pay upgrades with", None, pay)
        keep = spin("keep_gold", int(u.get("keep", {}).get("gold", 500000) or 0), 0, 50_000_000)
        keep.setSingleStep(100_000)
        keep.setGroupSeparatorShown(True)
        row(g, "Always keep gold", "Searching for bases costs gold", keep)
        row(g, "Choose upgrades by", None,
            combo("upgrade_order", [("The game's order", "game"), ("My list, top first", "mine")],
                  u.get("order", "game")))
        g.addWidget(_label("Tick what may be upgraded, and drag (or Up / Down) to set your order. The game's order: "
                           "what the game suggests first, unticked ones skipped. My list: only ticked ones, the "
                           "highest that can be paid first (the whole Build list is read). The Town Hall and heroes "
                           "start unticked (after a Town Hall upgrade, change its level on the Accounts page); walls "
                           "are never upgraded.", "help", wrap=True),
                    g.rowCount(), 0, 1, 2)
        lst = self.upgrade_list = QListWidget()
        lst.setDragDropMode(QAbstractItemView.InternalMove)
        lst.setDefaultDropAction(Qt.MoveAction)
        lst.setSelectionMode(QAbstractItemView.SingleSelection)
        lst.setFixedHeight(290)
        lst.itemChanged.connect(lambda _: self._set_dirty(True))
        lst.model().rowsMoved.connect(lambda *_: self._set_dirty(True))
        g.addWidget(lst, g.rowCount(), 0, 1, 2)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        tools.addWidget(_button("", "arrow-up", slot=lambda: self._move_upgrade(-1), tip="Move up"))
        tools.addWidget(_button("", "arrow-down", slot=lambda: self._move_upgrade(1), tip="Move down"))
        tools.addWidget(_button("All", "check", slot=lambda: self._tick_upgrades(True), tip="Tick every building"))
        tools.addWidget(_button("None", "x-circle", slot=lambda: self._tick_upgrades(False), tip="Untick all"))
        tools.addSpacing(8)
        self.upgrade_new = QLineEdit(placeholderText="Another name, e.g. Giga Inferno")
        self.upgrade_new.returnPressed.connect(self._add_upgrade)
        tools.addWidget(self.upgrade_new, 1)
        tools.addWidget(_button("Add", "plus", slot=self._add_upgrade, tip="Add a name the list does not have"))
        tools.addWidget(_button("", "trash", slot=self._remove_upgrade, tip="Remove a name you added"))
        g.addLayout(tools, g.rowCount(), 0, 1, 2)
        self._fill_upgrade_list(upgrade.plan(u))

        g = section("Clan Capital raid", "castle", right)
        g.addWidget(_label("On Raid Weekend each account opens the Capital by the airship, sets its army to Super "
                           "Miners, 1 Frost and 2 Graveyard (first attack only), taps the districts from Barbarian "
                           "Camp on until one has a red Attack, drops the miners on that district's free deploy spot "
                           "and the spells inside it, then closes and reopens the game instead of waiting for the "
                           "battle.", "help", wrap=True), g.rowCount(), 0, 1, 2)
        row(g, "Raid attacks per account", "5 each weekend, 6 with the bonus attack",
            spin("raid_attacks", s.get("raid", {}).get("attacks", 6), 1, 6))
        learned = QWidget()
        ll = QHBoxLayout(learned)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        self.learned_text = _label("", "muted")
        ll.addWidget(self.learned_text)
        ll.addWidget(_button("Forget", "trash", slot=self._forget_raid,
                             tip="Forget where the districts and their deploy spots are: they are found again"))
        row(g, "Learned places", "Each district's place on the raid map and its deploy spot, found once and then "
                                 "tapped straight away", learned)
        self._show_learned()

        g = section("Device", "monitor", right)
        row(g, "BlueStacks instance", "Empty = the main instance (clones are Pie64_1 ...)",
            edit("bluestacks_instance", s["device"].get("bluestacks_instance", ""), "main instance"))
        row(g, "Screenshots of problems", "Saved in logs/errors", check("save_error_screenshots",
                                                                        s.get("save_error_screenshots", True)))
        tools = QWidget()
        tl = QHBoxLayout(tools)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)
        tl.addWidget(_button("Restart the game", "play", slot=self.restart_game,
                             tip="Close Clash of Clans and open it again (BlueStacks is started if it is closed)"))
        tl.addWidget(_button("Close BlueStacks", "x-circle", slot=self.close_bluestacks, tip="Close BlueStacks now"))
        row(g, "Now", "When the game hangs or you want a fresh start", tools)
        right.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        return scroll

    def _fill_donate(self):
        """The account lists of the Loot + donate card (#position, name)."""
        d = self.settings.get("donate", {})
        names = [(f"#{i}  {a['name']}", i) for i, a in enumerate(self.accounts, 1)]
        main_val = d.get("main", 1)
        partner_val = d.get("partner", 2)
        for key, first, value in (("donate_main", ("None (other PC)", 0), 1 if main_val is None else main_val),
                                  ("donate_partner", ("No partner", 0), 0 if partner_val is None else partner_val)):
            c = self.f[key]
            c.blockSignals(True)
            c.clear()
            for text, data in ([first] if first else []) + names:
                c.addItem(text, data)
            c.setCurrentIndex(max(0, c.findData(int(value))))
            c.blockSignals(False)

    # the Loot + upgrade list ------------------------------------------------------------------------------
    def _fill_upgrade_list(self, entries):
        lst = self.upgrade_list
        lst.blockSignals(True)
        lst.clear()
        for name, on in entries:
            group = upgrade.GROUP.get(name)
            item = QListWidgetItem(f"{name}   ·   {group}" if group else f"{name}   ·   added by you")
            item.setData(Qt.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            item.setFlags(item.flags() & ~Qt.ItemIsDropEnabled)
            item.setCheckState(Qt.Checked if on else Qt.Unchecked)
            if group == "Hero":
                item.setToolTip("A hero cannot fight while it upgrades")
            elif group == "Town Hall":
                item.setToolTip("After a Town Hall upgrade, change its level on the Accounts page")
            lst.addItem(item)
        lst.blockSignals(False)

    def _upgrade_entries(self):
        lst = self.upgrade_list
        return [{"name": lst.item(i).data(Qt.UserRole), "on": lst.item(i).checkState() == Qt.Checked}
                for i in range(lst.count())]

    def _move_upgrade(self, d):
        lst = self.upgrade_list
        r = lst.currentRow()
        if r < 0 or not 0 <= r + d < lst.count():
            return
        item = lst.takeItem(r)
        lst.insertItem(r + d, item)
        lst.setCurrentRow(r + d)
        self._set_dirty(True)

    def _tick_upgrades(self, on):
        lst = self.upgrade_list
        for i in range(lst.count()):
            lst.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def _add_upgrade(self):
        name = self.upgrade_new.text().strip()
        if not name:
            return
        entries = self._upgrade_entries()
        if any(upgrade.key(e["name"]) == upgrade.key(name) for e in entries):
            self.toasts.show(f"{name} is in the list already", "info")
            return
        self._fill_upgrade_list([(name, True)] + [(e["name"], e["on"]) for e in entries])
        self.upgrade_list.setCurrentRow(0)
        self.upgrade_new.clear()
        self._set_dirty(True)

    def _remove_upgrade(self):
        item = self.upgrade_list.currentItem()
        if item is None:
            return
        if item.data(Qt.UserRole) in upgrade.CATALOG:
            self.toasts.show("Buildings of the game stay in the list: untick it instead", "info")
            return
        self.upgrade_list.takeItem(self.upgrade_list.row(item))
        self._set_dirty(True)

    RAID_MEMORY = ("raid_map_", "raid_spots_", "raid_airship_")

    def _show_learned(self):
        state = config.load_state()
        spots = sum(len(v) for k, v in state.items() if k.startswith("raid_spots_") and isinstance(v, dict))
        places = sum(len(v) for k, v in state.items() if k.startswith("raid_map_") and isinstance(v, dict))
        self.learned_text.setText(f"{places} on the map, {spots} deploy spots" if spots or places else "Nothing yet")

    def _forget_raid(self):
        state = config.load_state()
        for k in [k for k in state if k.startswith(self.RAID_MEMORY)]:
            state.pop(k)
        config.save_state(state)
        self._show_learned()
        self.toasts.show("Learned raid places forgotten: they are found again on the next raid", "info")

    # --- storage & loot ------------------------------------------------------------------------------
    def _storage_page(self):
        card = Card()
        card.body.addWidget(_label("Full storage: an account is full when the resource you fill reaches this amount. "
                                   "Minimum loot: a base is attacked only when it has at least this much. 'default' "
                                   "is the minimum for every Town Hall without its own row.", "muted", wrap=True))
        cols = [f"Full {RES_NAME[r].lower()}" for r in RESOURCES] + [f"Min {RES_NAME[r].lower()}" for r in RESOURCES]
        t = self.th_table = QTableWidget(0, len(cols))
        for c, text in enumerate(cols):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)
            t.setHorizontalHeaderItem(c, item)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        t.verticalHeader().setDefaultSectionSize(38)
        t.verticalHeader().setMinimumWidth(80)
        t.setShowGrid(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.itemChanged.connect(self._th_item_changed)
        full, mins = self.settings["full_at"], self.settings["min_loot"]
        ths = sorted({k for k in list(full) + list(mins) if k.isdigit()}, key=int, reverse=True) + ["default"]
        for th in ths:
            self._add_th_row(th, full.get(th, {}), mins.get(th, {}))
        card.body.addWidget(t, 1)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.new_th = _spinbox(1, 19, 10)
        self.new_th.setPrefix("TH ")
        bar.addWidget(self.new_th)
        bar.addWidget(_button("Add Town Hall", "plus", slot=self._new_th_row))
        bar.addWidget(_button("Remove selected", "trash", slot=self._remove_th_rows))
        bar.addStretch(1)
        card.body.addLayout(bar)
        return card

    def _add_th_row(self, th, full, mins):
        t = self.th_table
        head = th if th == "default" else f"TH {th}"
        if any(t.verticalHeaderItem(r).text() == head for r in range(t.rowCount())):
            return
        t.blockSignals(True)
        r = t.rowCount()
        if th != "default":                             # keep the Town Halls high to low, default last
            for i in range(t.rowCount()):
                other = t.verticalHeaderItem(i).text()
                if other == "default" or int(other[3:]) < int(th):
                    r = i
                    break
        t.insertRow(r)
        t.setVerticalHeaderItem(r, QTableWidgetItem(head))
        for i, res in enumerate(RESOURCES):
            item = QTableWidgetItem(_fmt(full.get(res, 0)) if th != "default" else "")
            if th == "default":
                item.setFlags(Qt.NoItemFlags)           # no full storage for an unknown Town Hall
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor(RES_COLOR[res]))  # the numbers in their resource's colour
            t.setItem(r, i, item)
            m = QTableWidgetItem(_fmt(mins.get(res, 0)))
            m.setTextAlignment(Qt.AlignCenter)
            m.setForeground(QColor(RES_COLOR[res]))
            t.setItem(r, 3 + i, m)
        t.blockSignals(False)

    def _th_item_changed(self, item):
        self.th_table.blockSignals(True)
        item.setText(_fmt(_int(item.text())))
        self.th_table.blockSignals(False)
        self._set_dirty(True)

    def _new_th_row(self):
        self._add_th_row(str(self.new_th.value()), {}, {})
        self._set_dirty(True)

    def _remove_th_rows(self):
        rows = sorted({i.row() for i in self.th_table.selectedIndexes()}, reverse=True)
        for r in rows:
            if self.th_table.verticalHeaderItem(r).text() != "default":
                self.th_table.removeRow(r)
                self._set_dirty(True)

    # --- log -----------------------------------------------------------------------------------------
    def _log_page(self):
        card = Card()
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.log_filter = QComboBox()
        self.log_filter.addItem("Every step (detailed)", "steps")
        self.log_filter.addItem("Main events", "all")
        self.log_filter.addItem("Warnings and errors", "warn")
        self.log_filter.setFixedWidth(200)
        self.log_filter.currentIndexChanged.connect(self._refilter_log)
        bar.addWidget(self.log_filter)
        bar.addStretch(1)
        bar.addWidget(_button("Clear", "trash", slot=self._clear_log))
        bar.addWidget(_button("Open log file", "terminal",
                              slot=lambda: self._open(os.path.join(paths.LOGS, "bot.log"))))
        bar.addWidget(_button("Error screenshots", "folder", slot=lambda: self._open(paths.ERROR_SHOTS)))
        card.body.addLayout(bar)
        self.log_view = QPlainTextEdit(readOnly=True, objectName="log")
        self.log_view.setMaximumBlockCount(6000)
        card.body.addWidget(self.log_view, 1)
        return card

    def _open(self, path):
        if os.path.exists(path):
            os.startfile(path)

    def _clear_log(self):
        self.lines.clear()
        self.log_view.clear()

    def _refilter_log(self):
        self.log_view.clear()
        for level, text in self.lines:
            self._show_line(self.log_view, level, text)

    def _show_line(self, view, level, text):
        shown = "steps" if view is self.log_view else "all"              # Recent activity: the main events
        if view is self.log_view:
            shown = self.log_filter.currentData()
        if shown == "warn" and level not in ("WARNING", "ERROR", "CRITICAL") or shown == "all" and level == "DEBUG":
            return
        colour = {"WARNING": AMBER, "ERROR": RED, "CRITICAL": RED, "DEBUG": DIM}.get(level)
        stamp, _, msg = text.partition("  ")
        msg = msg.replace("&", "&amp;").replace("<", "&lt;")
        body = f'<span style="color:{colour}">{msg}</span>' if colour else msg
        view.appendHtml(f'<span style="color:{DIM}">{stamp}</span>&nbsp;&nbsp;{body}')

    def append(self, level, text):
        self.lines.append((level, text))
        for view in (self.log_view, self.recent):
            bottom = view.verticalScrollBar().value() >= view.verticalScrollBar().maximum() - 4
            self._show_line(view, level, text)
            if bottom:
                view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
        if level in ("ERROR", "CRITICAL") and time.monotonic() - self._last_error_toast > 8:  # (DEBUG: never)
            self._last_error_toast = time.monotonic()      # a burst of errors: one toast
            self.toasts.show(text.partition("  ")[2][:160], "error", 6000)

    def note(self, text, level="INFO"):
        self.append(level, f"{time.strftime('%H:%M:%S')}  {text}")

    # --- saving --------------------------------------------------------------------------------------
    def _set_dirty(self, dirty):
        if self.loading:
            return
        self.dirty = dirty
        if dirty:
            self.save_state.setText("Unsaved changes")
            self.save_state.setStyleSheet(f"color: {AMBER};")
        else:
            self.save_state.setText("All changes saved")
            self.save_state.setStyleSheet(f"color: {DIM};")

    def collect(self):
        """The settings and accounts as shown in the window."""
        s = json.loads(json.dumps(self.settings))
        lo, f = s["loot"], self.f
        s["mode"] = self.mode.value()
        s["start_from"] = int(self.start_combo.currentData() or 1)
        s.setdefault("raid", {})["attacks"] = f["raid_attacks"].value()
        wl = s.setdefault("walls", {})
        wl["spend"] = {r: f[f"walls_{r}"].isChecked() for r in ("gold", "elixir")}
        wl["keep"] = {r: f[f"walls_keep_{r}"].value() for r in ("gold", "elixir")}
        u = s.setdefault("upgrade", {})
        u["spend"] = {r: f[f"spend_{r}"].isChecked() for r in RESOURCES}
        u.setdefault("keep", {})["gold"] = f["keep_gold"].value()
        u.pop("heroes", None)                           # (heroes are ticked in the list now)
        u["order"] = f["upgrade_order"].currentData()
        u["list"] = self._upgrade_entries()
        d = s.setdefault("donate", {})
        main_val = f["donate_main"].currentData()
        d["main"] = 1 if main_val is None else int(main_val)
        d["partner"] = int(f["donate_partner"].currentData() or 0)
        d.pop("request_to", None)
        d["request_top"] = f["donate_request_top"].value()
        d["need"] = f["donate_need"].value()
        d["poll_seconds"] = f["donate_poll_seconds"].value()
        d["empty_cc"] = f["donate_empty_cc"].isChecked()
        d["only_mine"] = f["donate_only_mine"].isChecked()
        s["repeat_rounds"] = f["repeat_rounds"].value()
        s["when_done"] = f["when_done"].currentData()
        s["another_device_wait"] = f["another_device_wait"].value()
        s["save_error_screenshots"] = f["save_error_screenshots"].isChecked()
        s["device"]["bluestacks_instance"] = f["bluestacks_instance"].text().strip()
        lo["watch"] = {r: f[f"watch_{r}"].isChecked() for r in RESOURCES}
        for key in ("full_rule", "min_loot_rule", "attack_plan"):
            lo[key] = f[key].currentData()
        for key in ("stuck_attacks", "max_attacks_per_account", "battle_seconds", "end_when_loot_stops",
                    "max_searches"):
            lo[key] = f[key].value()
        for key in ("smart_deploy", "count_troops", "zoom_out"):
            lo[key] = f[key].isChecked()
        full, mins = {}, {}
        for r in range(self.th_table.rowCount()):
            th = self.th_table.verticalHeaderItem(r).text().replace("TH ", "")
            vals = [_int(self.th_table.item(r, c).text()) for c in range(6)]
            if th != "default" and any(vals[:3]):
                full[th] = dict(zip(RESOURCES, vals[:3]))
            mins[th] = dict(zip(RESOURCES, vals[3:]))
        s["full_at"], s["min_loot"] = full, mins
        return s, self._accounts_from_table()

    def save(self, quiet=False):
        if self.thread is not None:
            return
        self.settings, self.accounts = self.collect()
        config.save_settings(self.settings)
        config.save_accounts(self.accounts)
        self.now_bar.set_res(self._watch_res())
        self._fill_dashboard_accounts()
        self._fill_start()
        self._fill_donate()
        was_dirty = self.dirty
        self._set_dirty(False)
        self.note(f"Saved the settings and {len(self.accounts)} accounts")
        if was_dirty and not quiet:
            self.toasts.show(f"Saved the settings and {len(self.accounts)} accounts", "success", 2400)

    # --- running -------------------------------------------------------------------------------------
    def _set_running(self, running):
        self.start_btn.setEnabled(not running)
        self.check_btn.setEnabled(not running)
        self.save_btn.setEnabled(not running)
        self.pause_btn.setEnabled(running)
        self.stop_btn.setEnabled(running)
        self.mode.setEnabled(not running)               # what runs is fixed at Start
        self.start_combo.setEnabled(not running and self.mode.value() not in DONATE_MODES)   # follows the run
        for i in (1, 2, 3):
            page = self.stack.widget(i)
            page.page.setEnabled(not running)          # read at Start: locked while running
            page.banner.setVisible(running)
        self._refresh()

    def _launch(self, target, label):
        self.save(quiet=True)
        if self.mode.value() in DONATE_MODES:
            if not self.accounts:
                self.note("No accounts are listed on the Accounts page", "WARNING")
                self.toasts.show("No accounts are listed on the Accounts page", "warning")
                self._go(1)
                return
        elif not any(a.get("enabled", True) for a in self.accounts):
            self.note("No account is ticked on the Accounts page", "WARNING")
            self.toasts.show("No account is ticked on the Accounts page", "warning")
            self._go(1)
            return
        control.reset()
        self.bot, self.started_at, self.ended_at = None, time.monotonic(), None
        self._fill_dashboard_accounts()
        self._go(0)
        self.note(f"{label} - the mouse is busy now (F9 pause, F10 stop)")
        self.toasts.show(f"{label}. The mouse is busy now: F9 pauses, F10 stops", "info")
        settings, accounts = json.loads(json.dumps(self.settings)), [dict(a) for a in self.accounts]

        def work():
            reason = "finished"
            try:
                reason = target(settings, accounts) or "finished"
            except Exception as e:  # noqa: BLE001 - e.g. BlueStacks not installed, ADB off
                log.error("%s", e)
                reason = "error"
            self.finished.emit(reason)

        self.thread = threading.Thread(target=work, daemon=True, name="bot")
        self._set_running(True)
        self.thread.start()

    def start(self):
        self.run_kind = "run"
        mode = self.mode.value()
        if mode in ("loot_donate", "donate_only"):
            where = "on the main account"
        elif mode == "request_only":
            where = "on the requesting accounts"
        else:
            where = f"from account #{self.start_combo.currentData() or 1}"
        self._launch(lambda s, a: runner.run(s, a, on_bot=self._got_bot),
                     f"{runner.MODES.get(mode, mode)} started {where}")

    def check(self):
        self.run_kind = "check"
        self._launch(lambda s, a: runner.check(s, a), "Checking the setup (no attack)")

    def restart_game(self):
        self.run_kind = "restart"
        self._launch(lambda s, a: runner.restart_only(s, a), "Restarting Clash of Clans")

    def close_bluestacks(self):
        self.run_kind = "close"
        self._launch(lambda s, a: runner.close_bluestacks_only(s, a), "Closing BlueStacks")

    def _got_bot(self, b):
        self.bot = b

    def stop(self):
        control.stop()
        doing = getattr(getattr(self, "bot", None), "action", "") or ""
        logging.getLogger("bot").info("Stop pressed (window)%s", f" during: {doing}" if doing else "")
        self.note("Stopping..." + (f" (after: {doing})" if doing else ""))

    def _come_back(self):
        """After a run (F10 too) BlueStacks still fills the screen: the window comes back in front of it."""
        if self.isMinimized():
            self.showMaximized()
        self.raise_()
        self.activateWindow()
        try:
            import win32con
            import win32gui

            from bot.device import bring_to_front
            hwnd = int(self.winId())
            flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, flags)     # over the full-screen game,
            win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags)   # without staying on top
            bring_to_front(hwnd)
        except Exception:  # noqa: BLE001 - the window is still there, just behind
            log.debug("Could not bring the window to the front", exc_info=True)

    def _on_finished(self, reason):
        self.thread = None
        self.ended_at = time.monotonic()
        self._come_back()
        if self.bot is not None:
            self._follow_start(getattr(self.bot, "start_from", 1))
        self._set_running(False)
        self._show_learned()
        self.note(f"Run {reason}", "WARNING" if reason == "error" else "INFO")
        kind = {"error": "error", "stopped": "warning"}.get(reason, "success")
        follows = reason != "error" and self.mode.value() not in DONATE_MODES
        self.toasts.show(f"Run {reason}" + (f" - the next run starts from account #{self.settings.get('start_from', 1)}"
                                            if follows else ""), kind, 5000)
        if reason == "finished" and getattr(self, "run_kind", "run") == "run":
            after = self.settings.get("when_done", "nothing")
            if after == "close_all":
                self.toasts.show("Every account is done: the bot closes in 5 s", "info", 5000)
                QTimer.singleShot(5000, self.close)
            elif after == "shutdown":                   # the game and BlueStacks are closed, the shutdown is set
                self.toasts.show(f"Every account is done: the PC shuts down in {runner.SHUTDOWN_DELAY} s. The bot "
                                 "closes now (to keep the PC on: Win+R, shutdown /a)", "warning", 5000)
                QTimer.singleShot(5000, self.close)

    def _refresh(self):
        running = self.thread is not None
        paused = running and control.paused
        state, colour = ("Paused", AMBER) if paused else ("Running", GREEN) if running else ("Stopped", DIM)
        self.status_dot.set(colour, running and not paused)
        self.shimmer.set_running(running and not paused)
        self.status_text.setText(state)
        self.status_text.setStyleSheet(f"color: {colour if running else TEXT};")
        self.pause_btn.setText("Continue" if paused else "Pause")
        self.pause_btn.setIcon(icons.icon("play" if paused else "pause", "#1a1205", 16))
        b = self.bot
        acc = b.current_acc if b else None
        mode = self.mode.value()
        self.status_sub.setText((acc["name"] if acc else "Starting...") if running else "Press Start to run")
        if b is not None and running:
            self._follow_start(getattr(b, "start_from", None) or self.settings.get("start_from", 1))
        active, when = raid.describe_window()
        tint = ORANGE if active else DIM
        self.raid_pill.setText(when)
        self.raid_pill.setStyleSheet(f"color: {tint}; background: {_rgba(tint, 0.13)}; "
                                     f"border: 1px solid {_rgba(tint, 0.4)};")

        stats = b.stats if b else {"attacks": 0, "raids": 0, "searches": 0, "loot": {}}
        self.stat_cards["attacks"].count(stats["attacks"])
        self.stat_cards["raids"].count(stats.get("raids", 0))
        self.stat_cards["searches"].count(stats["searches"])
        self.stat_cards["requests"].count(stats.get("requests", 0))
        self.stat_cards["donated"].count(stats.get("donated", 0))
        self.stat_cards["upgrades"].count(stats.get("upgrades", 0))
        self.stat_cards["walls"].count(stats.get("walls", 0))
        for r in RESOURCES:
            self.stat_cards[r].count(stats["loot"].get(r, 0))
        if self.started_at:
            secs = int((self.ended_at or time.monotonic()) - self.started_at)
            self.stat_cards["time"].set(f"{secs // 3600}:{secs // 60 % 60:02d}:{secs % 60:02d}")
        else:
            self.stat_cards["time"].set("0:00:00")

        res = self._watch_res()
        progress = b.progress if b else {}
        shown = [a for a, _, _, _ in self.dash_rows]
        done = sum(1 for a in shown if progress.get(a["name"], {}).get("status") in DONE)
        self.stat_cards["done"].set(f"{done} / {len(shown)}")
        looting = mode not in ("raid", "request_only")
        if acc:
            pos = next((i for i, a in enumerate(shown, 1) if a["name"] == acc["name"]), None)
            self.now_account.setText(acc["name"])
            p = progress.get(acc["name"], {})
            raids = f"   ·   {p['raids']} raid attack(s)" if p.get("raids") else ""
            where = f"   ·   account {pos} of {len(shown)}" if pos else ""
            if mode in DONATE_MODES:
                where = f"   ·   {self._donate_role(acc, mode)}"
            self.now_meta.setText(f"Town Hall {acc.get('th') or '?'}" + where + raids)
            value = (p.get("res") or {}).get(res)
            self.now_res_title.setText(f"{RES_NAME[res]} towards full storage" if looting else "")
            self.now_bar.set(value, config.full_at(self.settings, acc, res))
            self.now_bar.setVisible(looting)
        else:
            self.now_account.setText("Starting..." if running else "Not running")
            label = f"{len(shown)} accounts" if mode in DONATE_MODES else f"{len(shown)} accounts ticked"
            self.now_meta.setText(label + ("" if running else "   ·   press Start"))
            self.now_res_title.setText("")
            self.now_bar.hide()                         # no account yet: no bar
        self.last_row.setVisible(looting)
        action = (("Paused" if paused else b.action) if (b and running) else
                  ("Starting BlueStacks and the game" if running else "Idle"))
        clan = action.startswith(("Donat", "Request", "Waiting for the request"))
        building = action.startswith(("Upgrade", "Walls"))
        tint = (AMBER if paused else ORANGE if action.startswith("Raid") else ELIXIR if clan else
                GOLD if building else BLUE if running else DIM)
        self.now_action_fade.set(action, tint)
        self.now_icon.setPixmap(icons.pixmap("castle" if action.startswith("Raid") else "users" if clan else
                                             "arrow-up" if building else "bolt", tint, 16))
        last = b.last_loot if b else None
        for r in RESOURCES:
            self.last_vals[r].setText(short(last.get(r)) if last else "-")

        self._mark_current(acc["name"] if (acc and running) else None)
        for a, bar, chip, _ in self.dash_rows:
            p = progress.get(a["name"], {})
            bar.set((p.get("res") or {}).get(res), config.full_at(self.settings, a, res))
            status = p.get("status", "waiting")
            if status == "looting" and not (running and acc and acc["name"] == a["name"]):
                status = "waiting" if not p.get("res") else "looting"
            extra = ""
            if status in ("raided", "raiding") and p.get("raids"):
                extra = f"{p['raids']} attack{'s' if p['raids'] > 1 else ''}"
            elif status in ("donated", "donating") and p.get("donated"):
                extra = f"{p['donated']} units"
            if p.get("upgrades"):
                ups = f"{p['upgrades']} upgrade{'s' if p['upgrades'] > 1 else ''}"
                extra = f"{extra}  ·  {ups}" if extra else ups
            if p.get("walls"):
                ws = f"{p['walls']} wall{'s' if p['walls'] > 1 else ''}"
                extra = f"{extra}  ·  {ws}" if extra else ws
            chip.set(status, extra)

    def _donate_role(self, acc, mode="loot_donate"):
        """What an account does in the donate modes."""
        if mode == "donate_only":
            return "main account: donates and loots"
        if mode == "request_only":
            return "requests troops"
        d = self.settings.get("donate", {})
        pos = next((i for i, a in enumerate(self.accounts, 1) if a["name"] == acc["name"]), 0)
        if pos == int(d.get("main", 1) or 0):
            return "main account: donates"
        if pos == int(d.get("partner", 2) or 0):
            return "partner: loots with the main account, requests"
        return "requests troops"

    # --- window ---------------------------------------------------------------------------------------
    def showEvent(self, e):
        super().showEvent(e)
        try:                                            # dark Windows title bar
            ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 20, ctypes.byref(ctypes.c_int(1)), 4)
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, e):
        if self.thread is not None:
            control.stop()
            self.thread.join(timeout=5)
        e.accept()


def main(start=False):
    """The window; start=True presses Start once it is open."""
    app = QApplication(sys.argv)
    app.setApplicationName("COC Bot")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(icons.app_icon())
    try:                                                # its own taskbar icon instead of python's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("COCBot.Window")
    except Exception:  # noqa: BLE001
        pass
    runner.setup_logging(console=False)
    bridge = LogBridge()
    log.addHandler(bridge)
    w = Window()
    bridge.line.connect(w.append)
    keys = w.settings.get("hotkeys", {})
    control.start_hotkeys(keys.get("pause", "f9"), keys.get("stop", "f10"))
    motion.fade_window(w)
    w.showMaximized()                                   # always opens maximized
    if start:
        QTimer.singleShot(1500, w.start)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main("--start" in sys.argv))
