"""Line icons (24x24 SVG, the same set as Coc-Bot's window) in any colour, and the gold / elixir / dark elixir
glyphs."""

from functools import lru_cache

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtSvg import QSvgRenderer

# stroke icons (fill="none")
_STROKE = {
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1.6"/><rect x="14" y="3" width="7" height="5" rx="1.6"/>'
                 '<rect x="14" y="12" width="7" height="9" rx="1.6"/><rect x="3" y="16" width="7" height="5" rx="1.6"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "swords": '<path d="M14.5 17.5 3 6V3h3l11.5 11.5"/><path d="m13 19 6-6"/><path d="m16 16 4 4"/>'
              '<path d="m19 21 2-2"/><path d="M14.5 6.5 18 3h3v3l-3.5 3.5"/><path d="m5 14 4 4"/>'
              '<path d="m7 17-3 3"/><path d="m3 19 2 2"/>',
    "scan": '<path d="M3 7.5V6a3 3 0 0 1 3-3h1.5"/><path d="M16.5 3H18a3 3 0 0 1 3 3v1.5"/>'
            '<path d="M21 16.5V18a3 3 0 0 1-3 3h-1.5"/><path d="M7.5 21H6a3 3 0 0 1-3-3v-1.5"/>'
            '<rect x="7.5" y="7.5" width="9" height="9" rx="1.5"/>',
    "terminal": '<rect x="2" y="3" width="20" height="18" rx="2.5"/><path d="m7 9 3 3-3 3"/><path d="M13 15h4"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "trash": '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
             '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M10 11v6"/><path d="M14 11v6"/>',
    "arrow-up": '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>',
    "arrow-down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "check-circle": '<circle cx="12" cy="12" r="10"/><path d="m8 12.5 2.8 2.8L16 9.5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "sliders": '<path d="M4 21v-7"/><path d="M4 10V3"/><path d="M12 21v-9"/><path d="M12 8V3"/><path d="M20 21v-5"/>'
               '<path d="M20 12V3"/><path d="M1 14h6"/><path d="M9 8h6"/><path d="M17 16h6"/>',
    "layers": '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>'
            '<path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>',
    "list": '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.5"/><path d="M3 12h.5"/>'
            '<path d="M3 18h.5"/>',
    "monitor": '<rect x="2" y="3" width="20" height="14" rx="2.2"/><path d="M8 21h8"/><path d="M12 17v4"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "bolt": '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
    "keyboard": '<rect x="2" y="5" width="20" height="14" rx="2.2"/><path d="M6 9h1"/><path d="M10 9h1"/>'
                '<path d="M14 9h1"/><path d="M18 9h1"/><path d="M7 15h10"/>',
    "castle": '<path d="M3 21h18"/><path d="M5 21V10h2V7h2v3h2V5h2v5h2V7h2v3h2v11"/><path d="M10 21v-4h4v4"/>',
    "flag": '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22v-7"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "alert": '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>'
             '<path d="M12 9v4"/><path d="M12 17h.01"/>',
    "x-circle": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
}

# filled icons (stroke="none")
_FILL = {
    "play": '<path d="M7 4.6v14.8a1.1 1.1 0 0 0 1.66.95l12.3-7.4a1.1 1.1 0 0 0 0-1.9L8.66 3.65A1.1 1.1 0 0 0 7 4.6z"/>',
    "pause": '<rect x="5.5" y="4" width="4.6" height="16" rx="1.4"/><rect x="13.9" y="4" width="4.6" height="16" rx="1.4"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="2.8"/>',
    "dot": '<circle cx="12" cy="12" r="5"/>',
}


def svg(name, color):
    hexc = QColor(color).name()
    if name in _FILL:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="{hexc}" stroke="none">'
                f'{_FILL[name]}</g></svg>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="none" stroke="{hexc}" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{_STROKE[name]}</g></svg>')


@lru_cache(maxsize=256)
def _renderer(name, color):
    return QSvgRenderer(QByteArray(svg(name, color).encode()))


@lru_cache(maxsize=256)
def pixmap(name, color, size=18, dpr=1.25):
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    _renderer(name, color).render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name, color, size=18):
    """A QIcon (crisp at 100-200 % display scaling)."""
    ic = QIcon()
    for dpr in (1.0, 1.25, 1.5, 2.0):
        ic.addPixmap(pixmap(name, color, size, dpr))
    return ic


def _drop_path(r):
    w = r.width()
    cx = r.center().x()
    mid = r.bottom() - w / 2
    path = QPainterPath(QPointF(cx, r.top()))
    path.cubicTo(cx + w * 0.16, r.top() + r.height() * 0.2, r.right(), mid - w * 0.32, r.right(), mid)
    path.arcTo(QRectF(r.left(), r.bottom() - w, w, w), 0, -180)
    path.cubicTo(r.left(), mid - w * 0.32, cx - w * 0.16, r.top() + r.height() * 0.2, cx, r.top())
    path.closeSubpath()
    return path


def paint_resource(p, res, rect):
    """A small game-like glyph: gold coin, pink elixir drop, dark elixir drop."""
    r = QRectF(rect)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if res == "gold":
        g = QRadialGradient(r.center() - QPointF(r.width() * 0.18, r.height() * 0.2), r.width() * 0.75)
        g.setColorAt(0, QColor("#fff1b0"))
        g.setColorAt(0.45, QColor("#f8c845"))
        g.setColorAt(1, QColor("#c47a0c"))
        p.setPen(QPen(QColor("#8a5206"), max(1.0, r.width() * 0.06)))
        p.setBrush(g)
        p.drawEllipse(r.adjusted(1, 1, -1, -1))
        p.setPen(QPen(QColor(255, 244, 200, 150), max(1.0, r.width() * 0.05)))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(r.adjusted(r.width() * 0.24, r.height() * 0.24, -r.width() * 0.24, -r.height() * 0.24))
    else:
        top, bottom, edge = (("#f7a8ff", "#a62ac4", "#5d1170") if res == "elixir"
                             else ("#9d8ee0", "#2f2558", "#140f2a"))
        dr = r.adjusted(r.width() * 0.14, 0.5, -r.width() * 0.14, -0.5)
        g = QLinearGradient(dr.topLeft(), dr.bottomRight())
        g.setColorAt(0, QColor(top))
        g.setColorAt(1, QColor(bottom))
        p.setPen(QPen(QColor(edge), max(1.0, r.width() * 0.05)))
        p.setBrush(g)
        p.drawPath(_drop_path(dr))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 120))
        p.drawEllipse(QRectF(dr.left() + dr.width() * 0.22, dr.bottom() - dr.width() * 0.78, dr.width() * 0.2,
                             dr.width() * 0.32))
    p.restore()


def app_icon():
    """Crossed swords in gold on a dark rounded square."""
    ic = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1c2139"))
        p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
        m = size * 0.18
        _renderer("swords", "#f5b942").render(p, QRectF(m, m, size - 2 * m, size - 2 * m))
        p.end()
        ic.addPixmap(pm)
    return ic
