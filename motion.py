"""Animated pieces of the window: page transitions, the sliding sidebar highlight, a segmented switch, the
pulsing status dot, the "working" shimmer, count-up numbers, glowing buttons, staggered fade-ins and toasts.

Every animation is short and runs on Qt's own animation clock in the window's thread, so the bot (in its own
thread) is never held up by them.
"""

from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QEvent, QObject, QParallelAnimationGroup, QPoint,
                            QPointF, QPropertyAnimation, QRectF, Qt, QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

OUT = QEasingCurve.OutCubic


def _rgba(color, alpha):
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha:.3f})"


def _anim(target, prop, start, end, ms, curve=OUT, parent=None):
    a = QPropertyAnimation(target, prop, parent or target)
    a.setDuration(ms)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setEasingCurve(curve)
    return a


# ----------------------------------------------------------------------------- pages
class AnimatedStack(QStackedWidget):
    """A page that is chosen fades in while rising a few pixels into place."""

    def __init__(self, duration=280, rise=18):
        super().__init__()
        self.duration, self.rise = duration, rise
        self._running = None                            # (group, page)

    def show_page(self, i, animate=True):
        if i == self.currentIndex():
            return
        self._finish()
        self.setCurrentIndex(i)
        page = self.widget(i)
        if not animate or not self.isVisible():
            return
        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.0)
        page.setGraphicsEffect(effect)
        home = self.contentsRect().topLeft()
        group = QParallelAnimationGroup(self)
        group.addAnimation(_anim(effect, b"opacity", 0.0, 1.0, self.duration, parent=group))
        group.addAnimation(_anim(page, b"pos", home + QPoint(0, self.rise), home, self.duration + 80, parent=group))
        group.finished.connect(self._finish)
        self._running = (group, page)
        group.start()

    def _finish(self):
        if not self._running:
            return
        group, page = self._running
        self._running = None
        group.stop()
        group.deleteLater()
        page.setGraphicsEffect(None)
        page.move(self.contentsRect().topLeft())


class NavRail(QWidget):
    """The sidebar's page buttons; a highlight with a gold edge slides to the chosen one."""

    def __init__(self):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(4)
        self.pill = QFrame(self, objectName="navPill")
        self.edge = QFrame(self.pill, objectName="navEdge")
        self.pill.lower()
        self.buttons = []
        self.current = -1
        self.slide = QPropertyAnimation(self.pill, b"geometry", self)
        self.slide.setDuration(300)
        self.slide.setEasingCurve(OUT)

    def add(self, button):
        self.lay.addWidget(button)
        self.buttons.append(button)

    def select(self, i, animate=True):
        self.current = i
        target = self.buttons[i].geometry()
        self.slide.stop()
        if animate and self.isVisible() and self.pill.width() > 0:
            self.slide.setStartValue(self.pill.geometry())
            self.slide.setEndValue(target)
            self.slide.start()
        else:
            self.pill.setGeometry(target)
        self.edge.setGeometry(0, 10, 3, max(4, target.height() - 20))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.current >= 0:                           # after the layout placed the buttons
            QTimer.singleShot(0, lambda: self.select(self.current, animate=False))


class Segmented(QFrame):
    """A row of choices with a highlight that slides to the chosen one (in that choice's colour)."""
    changed = Signal(object)

    def __init__(self, items):
        """items: [(text, icon, data, colour)]; icon is a QIcon or None."""
        super().__init__(objectName="segmented")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        self.pill = QFrame(self, objectName="segPill")
        self.pill.lower()
        self.items, self.buttons = items, []
        for i, (text, icon, _, _) in enumerate(items):
            b = QPushButton(text, objectName="seg", checkable=True)
            if icon is not None:
                b.setIcon(icon)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self._pick(i))
            lay.addWidget(b)
            self.buttons.append(b)
        self.index = 0
        self.slide = QPropertyAnimation(self.pill, b"geometry", self)
        self.slide.setDuration(280)
        self.slide.setEasingCurve(OUT)

    def value(self):
        return self.items[self.index][2]

    def set_value(self, data, animate=False):
        i = next((k for k, it in enumerate(self.items) if it[2] == data), 0)
        self._select(i, animate)

    def _pick(self, i):
        changed = i != self.index
        self._select(i, True)
        if changed:
            self.changed.emit(self.value())

    def _select(self, i, animate):
        self.index = i
        colour = self.items[i][3]
        for k, b in enumerate(self.buttons):
            b.setChecked(k == i)
            b.setStyleSheet(f"color: {colour};" if k == i else "")
        self.pill.setStyleSheet(f"background: {_rgba(colour, 0.16)}; border: 1px solid {_rgba(colour, 0.55)}; "
                                f"border-radius: 8px;")
        target = self.buttons[i].geometry()
        self.slide.stop()
        if animate and self.isVisible() and self.pill.width() > 0:
            self.slide.setStartValue(self.pill.geometry())
            self.slide.setEndValue(target)
            self.slide.start()
        else:
            self.pill.setGeometry(target)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, lambda: self._select(self.index, False))


# ----------------------------------------------------------------------------- live indicators
class PulseDot(QWidget):
    """A status dot; while the bot runs a ring keeps spreading out of it."""

    def __init__(self, size=18):
        super().__init__()
        self.setFixedSize(size, size)
        self.color = QColor("#636c91")
        self.t = 0.0
        self.anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1600, loopCount=-1)
        self.anim.valueChanged.connect(self._tick)

    def _tick(self, v):
        self.t = float(v)
        self.update()

    def set(self, color, pulsing):
        self.color = QColor(color)
        if pulsing and self.anim.state() != QAbstractAnimation.Running:
            self.anim.start()
        elif not pulsing and self.anim.state() == QAbstractAnimation.Running:
            self.anim.stop()
            self.t = 0.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        c = QPointF(self.width() / 2, self.height() / 2)
        r = 4.0
        if self.anim.state() == QAbstractAnimation.Running:
            ring = QColor(self.color)
            ring.setAlphaF(0.55 * (1 - self.t))
            p.setBrush(ring)
            rr = r + (self.width() / 2 - r) * self.t
            p.drawEllipse(c, rr, rr)
        p.setBrush(self.color)
        p.drawEllipse(c, r, r)
        p.end()


class Shimmer(QWidget):
    """A thin line with a light running along it while the bot works (nothing is drawn when it is idle)."""

    def __init__(self, color, height=3):
        super().__init__()
        self.setFixedHeight(height)
        self.color = QColor(color)
        self.t = 0.0
        self.anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1700, loopCount=-1)
        self.anim.setEasingCurve(QEasingCurve.InOutSine)
        self.anim.valueChanged.connect(self._tick)

    def _tick(self, v):
        self.t = float(v)
        self.update()

    def set_color(self, color):
        self.color = QColor(color)
        self.update()

    def set_running(self, on):
        if on and self.anim.state() != QAbstractAnimation.Running:
            self.anim.start()
        elif not on and self.anim.state() == QAbstractAnimation.Running:
            self.anim.stop()
        self.update()

    def paintEvent(self, _):
        if self.anim.state() != QAbstractAnimation.Running:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        w, h = self.width(), self.height()
        base = QColor(self.color)
        base.setAlphaF(0.12)
        p.setBrush(base)
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        band = w * 0.32
        x = -band + self.t * (w + band)
        g = QLinearGradient(x, 0, x + band, 0)
        clear = QColor(self.color)
        clear.setAlphaF(0.0)
        g.setColorAt(0.0, clear)
        g.setColorAt(0.5, self.color)
        g.setColorAt(1.0, clear)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(x, 0, band, h), h / 2, h / 2)
        p.end()


class CountUp(QObject):
    """A label whose number counts up (or down) to each new value instead of jumping."""

    def __init__(self, label, fmt=str, ms=750):
        super().__init__(label)
        self.label, self.fmt = label, fmt
        self.value = 0.0
        self.shown = 0.0
        self.anim = QVariantAnimation(self, duration=ms, easingCurve=OUT)
        self.anim.valueChanged.connect(self._tick)
        label.setText(fmt(0))

    def _tick(self, v):
        self.shown = float(v)
        self.label.setText(self.fmt(int(round(self.shown))))

    def set(self, value):
        value = float(value or 0)
        if value == self.value:
            return
        self.value = value
        self.anim.stop()
        self.anim.setStartValue(self.shown)
        self.anim.setEndValue(value)
        self.anim.start()


class FadeText(QObject):
    """A label whose new text fades in (its colour goes from clear to `color`)."""

    def __init__(self, label, color, ms=380):
        super().__init__(label)
        self.label, self.color = label, QColor(color)
        self.anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=ms, easingCurve=OUT)
        self.anim.valueChanged.connect(self._tick)

    def _tick(self, v):
        c = QColor(self.color)
        c.setAlphaF(float(v))
        self.label.setStyleSheet(f"color: {c.name(QColor.HexArgb)};")

    def set(self, text, color=None):
        if color is not None and QColor(color) != self.color:
            self.color = QColor(color)
            self._tick(1.0)
        if text == self.label.text():
            return
        self.label.setText(text)
        self.anim.stop()
        self.anim.start()


class Flash(QObject):
    """A short glow of a chip's background when its status changes: from bright to its resting tint."""

    def __init__(self, label, ms=900):
        super().__init__(label)
        self.label = label
        self.color, self.extra = QColor("#98a1c3"), ""
        self.anim = QVariantAnimation(self, startValue=1.0, endValue=0.0, duration=ms, easingCurve=OUT)
        self.anim.valueChanged.connect(self._tick)

    def _tick(self, v):
        self.label.setStyleSheet(f"color: {self.color.name()}; background: {_rgba(self.color, 0.14 + 0.34 * v)}; "
                                 f"{self.extra}")

    def set(self, color, extra, animate=True):
        self.color, self.extra = QColor(color), extra
        self.anim.stop()
        if animate:
            self.anim.start()
        else:
            self._tick(0.0)


# ----------------------------------------------------------------------------- buttons
class Glow(QObject):
    """A soft glow in the button's colour: it grows while the mouse is on the button, and - with `breathe` -
    slowly swells and fades while the button waits to be pressed."""

    def __init__(self, button, color, breathe=False):
        super().__init__(button)
        self.button, self.breathe = button, breathe
        self.effect = QGraphicsDropShadowEffect(button)
        c = QColor(color)
        c.setAlpha(170)
        self.effect.setColor(c)
        self.effect.setOffset(0, 0)
        self.effect.setBlurRadius(0)
        button.setGraphicsEffect(self.effect)
        self.hover = QPropertyAnimation(self.effect, b"blurRadius", self)
        self.hover.setDuration(220)
        self.hover.setEasingCurve(OUT)
        self.hover.finished.connect(self._resume)
        self.breath = QVariantAnimation(self, duration=2600, loopCount=-1)
        self.breath.setStartValue(2.0)
        self.breath.setKeyValueAt(0.5, 20.0)
        self.breath.setEndValue(2.0)
        self.breath.setEasingCurve(QEasingCurve.InOutSine)
        self.breath.valueChanged.connect(lambda v: self.effect.setBlurRadius(float(v)))
        self.inside = False
        button.installEventFilter(self)
        QTimer.singleShot(400, self._resume)

    def _to(self, radius):
        self.breath.stop()
        self.hover.stop()
        self.hover.setStartValue(self.effect.blurRadius())
        self.hover.setEndValue(float(radius))
        self.hover.start()

    def _resume(self):
        on = self.breathe and self.button.isEnabled() and not self.inside
        if on and self.breath.state() != QAbstractAnimation.Running and \
                self.hover.state() != QAbstractAnimation.Running:
            self.breath.start()

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Enter and self.button.isEnabled():
            self.inside = True
            self._to(30)
        elif t == QEvent.Leave:
            self.inside = False
            self._to(2 if self.breathe and self.button.isEnabled() else 0)
        elif t == QEvent.EnabledChange:
            if self.button.isEnabled():
                QTimer.singleShot(0, self._resume)
            else:
                self.breath.stop()
                self.hover.stop()
                self.effect.setBlurRadius(0)
        return False


# ----------------------------------------------------------------------------- appearing
def fade_in(widgets, delay=80, ms=480):
    """Widgets appear one after another, each fading in (used once, when the window opens)."""
    for k, w in enumerate(widgets):
        effect = QGraphicsOpacityEffect(w)
        effect.setOpacity(0.0)
        w.setGraphicsEffect(effect)

        def go(w=w, effect=effect):
            a = _anim(effect, b"opacity", 0.0, 1.0, ms, parent=w)
            a.finished.connect(lambda w=w: w.setGraphicsEffect(None))
            a.start(QAbstractAnimation.DeleteWhenStopped)
        QTimer.singleShot(60 + k * delay, go)


def fade_window(window, ms=360):
    """The window fades in when it opens."""
    window.setWindowOpacity(0.0)
    a = _anim(window, b"windowOpacity", 0.0, 1.0, ms, parent=window)
    QTimer.singleShot(30, lambda: a.start(QAbstractAnimation.DeleteWhenStopped))


# ----------------------------------------------------------------------------- toasts
class Toasts(QObject):
    """Small notices that slide in at the bottom right of the window and fade away after a few seconds."""

    def __init__(self, host, colors, icon_for, surface, border, text):
        super().__init__(host)
        self.host, self.colors, self.icon_for = host, colors, icon_for
        self.surface, self.border, self.text = surface, border, text
        self.items = []
        host.installEventFilter(self)

    def show(self, message, kind="info", ms=3600):
        colour = self.colors.get(kind, self.text)
        t = QFrame(self.host)
        t.setObjectName("toast")
        t.setStyleSheet(f"QFrame#toast {{ background: {self.surface}; border: 1px solid {self.border}; "
                        f"border-left: 3px solid {colour}; border-radius: 10px; }}")
        lay = QHBoxLayout(t)
        lay.setContentsMargins(14, 11, 16, 11)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(self.icon_for(kind, colour))
        lay.addWidget(ic, 0, Qt.AlignTop)
        lbl = QLabel(message)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {self.text};")
        lay.addWidget(lbl, 1)
        t.setFixedWidth(360)
        t.adjustSize()
        effect = QGraphicsOpacityEffect(t)
        effect.setOpacity(0.0)
        t.setGraphicsEffect(effect)
        t.show()
        t.raise_()
        self.items.append(t)
        while len(self.items) > 4:
            self._drop(self.items[0], fast=True)
        t.glide = QPropertyAnimation(t, b"pos", t)     # one move animation per toast: a newer move replaces it
        t.glide.setEasingCurve(OUT)
        x, y = self._spot(t)
        t.move(x + 40, y)
        _anim(effect, b"opacity", 0.0, 1.0, 300, parent=t).start(QAbstractAnimation.DeleteWhenStopped)
        self._place()
        QTimer.singleShot(ms, lambda: self._drop(t))

    def _spot(self, toast):
        """Where a toast belongs: stacked upwards from the bottom right, the newest at the bottom."""
        y = self.host.height() - 22
        for t in reversed(self.items):
            y -= t.height()
            if t is toast:
                break
            y -= 10
        return self.host.width() - toast.width() - 24, y

    def _place(self, animate=True):
        for t in self.items:
            x, y = self._spot(t)
            t.glide.stop()
            if animate:
                t.glide.setDuration(360)
                t.glide.setStartValue(t.pos())
                t.glide.setEndValue(QPoint(x, y))
                t.glide.start()
            else:
                t.move(x, y)

    def _drop(self, t, fast=False):
        if t not in self.items:
            return
        self.items.remove(t)
        effect = t.graphicsEffect()
        a = _anim(effect, b"opacity", effect.opacity(), 0.0, 120 if fast else 320, parent=t)
        a.finished.connect(t.deleteLater)
        a.start(QAbstractAnimation.DeleteWhenStopped)
        self._place()

    def eventFilter(self, obj, ev):
        if obj is self.host and ev.type() == QEvent.Resize:
            self._place(animate=False)
        return False
