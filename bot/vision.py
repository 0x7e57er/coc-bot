"""Finding images on the screenshot: template matching, digit reading and text OCR.

Templates live in assets/templates/<group>/<name>.png (extra looks: <name>~2.png). Their search
region and threshold are in assets/templates/index.json, in base-screen (1920x1080) coordinates.
Matching uses OpenCV directly on one frame (the same algorithm pyautogui uses with confidence=,
without re-taking a screenshot for every image).
"""

import json
import os
import threading
from dataclasses import dataclass

import cv2
import numpy as np

from . import paths
from .space import space

DEFAULT_THRESHOLD = 0.85


@dataclass
class Match:
    x: int          # centre, game space
    y: int
    score: float
    box: tuple      # (left, top, w, h)

    @property
    def center(self):
        return self.x, self.y


class TemplateStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._images = {}
        self._variants = {}
        self.index = {}
        self.reload()

    def reload(self):
        with self._lock:
            self._images.clear()
            self._variants = {}
            if os.path.exists(paths.TEMPLATE_INDEX):
                with open(paths.TEMPLATE_INDEX, encoding="utf-8") as f:
                    self.index = json.load(f)
            else:
                self.index = {}

    def path(self, key):
        return os.path.join(paths.TEMPLATES, *key.split("/")) + ".png"

    def has(self, key):
        return os.path.exists(self.path(key))

    def variants(self, key):
        """The template and its extra looks (e.g. another scenery): key, key~2, key~3 ..."""
        v = self._variants.get(key)
        if v is None:
            p = self.path(key)
            folder, base = os.path.dirname(p), os.path.basename(p)[:-4]
            v = [key] if os.path.exists(p) else []
            if os.path.isdir(folder):
                for f in sorted(os.listdir(folder)):
                    if f.startswith(base + "~") and f.endswith(".png"):
                        v.append(key + f[len(base):-4])
            self._variants[key] = v
        return v

    def image(self, key):
        with self._lock:
            img = self._images.get(key)
            if img is None:
                p = self.path(key)
                if not os.path.exists(p):
                    raise FileNotFoundError(f"Template missing: {key}")
                img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
                self._images[key] = img
            return img

    def scaled(self, key, scale):
        """The template at another size (full-screen windows are drawn smaller on BlueStacks)."""
        if scale == 1.0:
            return self.image(key)
        k = (key, round(scale, 3))
        with self._lock:
            img = self._images.get(k)
        if img is None:
            interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
            img = cv2.resize(self.image(key), None, fx=scale, fy=scale, interpolation=interp)
            with self._lock:
                self._images[k] = img
        return img

    def meta(self, key):
        """A variant without its own settings uses the main template's (region, threshold)."""
        return self.index.get(key) or self.index.get(key.split("~")[0], {})


templates = TemplateStore()


def _crop(frame, region):
    if not region:
        return frame, 0, 0
    x, y, w, h = region
    x, y = max(0, int(x)), max(0, int(y))
    return frame[y:y + int(h), x:x + int(w)], x, y


def match_map(frame, key, region=None, scale=1.0):
    """Return (score map, offset_x, offset_y, template) for `key` (drawn `scale` x its size) searched in
    `region`."""
    tpl = templates.image(key) if scale == 1.0 else templates.scaled(key, scale)
    meta = templates.meta(key)
    if region is None and meta.get("region"):
        region = space.region(*meta["region"])
    area, ox, oy = _crop(frame, region)
    if area.shape[0] < tpl.shape[0] or area.shape[1] < tpl.shape[1]:
        area, ox, oy = frame, 0, 0
    res = cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED)
    return res, ox, oy, tpl


def _brightness_ok(frame, box, tpl):
    """Popups dim the screen behind them, but TM_CCOEFF_NORMED ignores brightness,
    so a button behind a popup still "matches". Reject matches much darker or
    brighter than the template."""
    x, y, w, h = box
    ratio = (frame[y:y + h, x:x + w].mean() + 1) / (tpl.mean() + 1)
    return 0.75 <= ratio <= 1.3


COARSE_AREA = 250_000      # areas bigger than this are searched coarse-to-fine
WINDOW_PAD = 30            # a window template's search region is grown by this much (game-space px)


def _search_region(key, region, window=None):
    """Where to look for `key`: the region given, else its region from index.json - pinned to the screen
    edges at full size, or placed like a full-screen window of that kind (space.windows)."""
    if region is not None:
        return region
    r = templates.meta(key).get("region")
    if not r:
        return None
    if window is None:
        return space.search_region(*r)
    x, y, w, h = space.window_region(*r, window=window)
    return x - WINDOW_PAD, y - WINDOW_PAD, w + 2 * WINDOW_PAD, h + 2 * WINDOW_PAD


def _coarse_fine(frame, key, region, window=None):
    """Same result as match_map + minMaxLoc, ~4x faster on big areas: find the best spot at half
    size, then measure the exact score at full size around it. `window`: look for it drawn like that
    kind of full-screen window (smaller, placed around the screen centre)."""
    tpl = templates.scaled(key, window[0] if window else 1.0)
    area, ox, oy = _crop(frame, _search_region(key, region, window))
    th, tw = tpl.shape[:2]
    if area.shape[0] < th or area.shape[1] < tw:
        area, ox, oy = frame, 0, 0
    if area.shape[0] * area.shape[1] < COARSE_AREA or min(th, tw) < 24:
        res = cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        return score, loc, ox, oy, tpl
    small = cv2.resize(area, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    tsmall = cv2.resize(tpl, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    res = cv2.matchTemplate(small, tsmall, cv2.TM_CCOEFF_NORMED)
    best = None
    # refine the 3 best coarse spots (a near-miss at half size can win at full size)
    for _ in range(3):
        _, s, _, loc = cv2.minMaxLoc(res)
        x, y = loc[0] * 2, loc[1] * 2
        x0, y0 = max(0, x - 6), max(0, y - 6)
        sub = area[y0:y0 + th + 12, x0:x0 + tw + 12]
        if sub.shape[0] >= th and sub.shape[1] >= tw:
            r2 = cv2.matchTemplate(sub, tpl, cv2.TM_CCOEFF_NORMED)
            _, s2, _, l2 = cv2.minMaxLoc(r2)
            if best is None or s2 > best[0]:
                best = (s2, (x0 + l2[0], y0 + l2[1]))
        lx, ly = loc
        res[max(0, ly - 4):ly + 5, max(0, lx - 4):lx + 5] = -1
    return best[0], best[1], ox, oy, tpl


def _find_one(frame, key, threshold, region, any_brightness):
    """The template at full size; if it is not there, as drawn in each kind of full-screen window (the
    army screen, the battle results ... are drawn smaller on BlueStacks than the PC picture)."""
    thr = threshold if threshold is not None else templates.meta(key).get("threshold", DEFAULT_THRESHOLD)
    for window in [None] + [w for w in space.windows if w[0] != 1.0]:
        score, loc, ox, oy, tpl = _coarse_fine(frame, key, region, window)
        if score < thr:
            continue
        h, w = tpl.shape[:2]
        x, y = loc[0] + ox, loc[1] + oy
        if not any_brightness and not _brightness_ok(frame, (x, y, w, h), tpl):
            continue
        return Match(x + w // 2, y + h // 2, float(score), (x, y, w, h))
    return None


def find(frame, key, threshold=None, region=None, any_brightness=False):
    """Best match of template `key` (or any of its variants), or None if below the
    threshold (or dimmed behind a popup)."""
    best = None
    for k in templates.variants(key) or [key]:
        m = _find_one(frame, k, threshold, region, any_brightness)
        if m and (best is None or m.score > best.score):
            best = m
    return best


def find_scaled(frame, key, scales=None, threshold=None, region=None):
    """Like find(), but tries the template at several sizes (for things drawn at different
    zoom levels, e.g. the boat icon). Returns (Match, scale) or (None, None)."""
    tpl0 = templates.image(key)
    meta = templates.meta(key)
    if region is None and meta.get("region"):
        region = space.region(*meta["region"])
    area, ox, oy = _crop(frame, region)
    thr = threshold if threshold is not None else meta.get("threshold", DEFAULT_THRESHOLD)
    best = (None, None)
    for sc in scales or [0.6 + 0.05 * i for i in range(17)]:
        tpl = cv2.resize(tpl0, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_LINEAR)
        if area.shape[0] < tpl.shape[0] or area.shape[1] < tpl.shape[1]:
            continue
        res = cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED)
        _, s, _, loc = cv2.minMaxLoc(res)
        if s >= thr and (best[0] is None or s > best[0].score):
            h, w = tpl.shape[:2]
            x, y = loc[0] + ox, loc[1] + oy
            best = (Match(x + w // 2, y + h // 2, float(s), (x, y, w, h)), sc)
    return best


def find_all(frame, key, threshold=None, region=None, max_results=20, any_brightness=False):
    """All non-overlapping matches above threshold, top to bottom: at full size, else as drawn in each kind of
    full-screen window (smaller on BlueStacks, like find())."""
    for scale in [1.0] + [w[0] for w in space.windows if w[0] != 1.0]:
        out = _find_all(frame, key, threshold, region, max_results, any_brightness, scale)
        if out:
            return out
    return []


def _find_all(frame, key, threshold, region, max_results, any_brightness, scale):
    res, ox, oy, tpl = match_map(frame, key, region, scale)
    thr = threshold if threshold is not None else templates.meta(key).get("threshold", DEFAULT_THRESHOLD)
    h, w = tpl.shape[:2]
    res = res.copy()
    out = []
    while len(out) < max_results:
        _, s, _, loc = cv2.minMaxLoc(res)
        if s < thr:
            break
        x, y = loc[0] + ox, loc[1] + oy
        if any_brightness or _brightness_ok(frame, (x, y, w, h), tpl):
            out.append(Match(x + w // 2, y + h // 2, float(s), (x, y, w, h)))
        x0, y0 = max(0, loc[0] - w // 2), max(0, loc[1] - h // 2)
        res[y0:loc[1] + h // 2 + 1, x0:loc[0] + w // 2 + 1] = -1
    out.sort(key=lambda m: (m.y, m.x))
    return out


# --- digit reader (resource numbers) -----------------------------------------------

class DigitReader:
    """Reads Clash of Clans numbers by comparing each digit with saved digit images.

    The game draws numbers in one fixed font (white / cream / pink fill with a dark
    outline), so this is faster and more reliable than general OCR.
    Digit images: assets/digits/<digit>_<anything>.png
    """

    SIZE = (24, 30)      # every glyph is normalised to this (w, h)
    ASPECT = 0.8         # glyphs are padded to this width/height ratio first
    MIN_LEVEL = 170      # a pixel is "text" when all three colour channels are this bright

    def __init__(self):
        self._templates = None

    def _load(self):
        out = []
        if os.path.isdir(paths.DIGITS):
            for name in sorted(os.listdir(paths.DIGITS)):
                if name.endswith(".png") and (name[0].isdigit() or name.startswith("slash")):
                    img = cv2.imdecode(np.fromfile(os.path.join(paths.DIGITS, name), dtype=np.uint8),
                                       cv2.IMREAD_GRAYSCALE)
                    out.append(("/" if name.startswith("slash") else name[0], cv2.resize(img, self.SIZE)))
        self._templates = out

    @property
    def ready(self):
        if self._templates is None:
            self._load()
        return len({d for d, _ in self._templates if d.isdigit()}) == 10

    def _normalise(self, glyph):
        h, w = glyph.shape
        target_w = max(w, int(round(h * self.ASPECT)))
        pad = target_w - w
        glyph = cv2.copyMakeBorder(glyph, 0, 0, pad // 2, pad - pad // 2, cv2.BORDER_CONSTANT, value=0)
        return cv2.resize(glyph, self.SIZE, interpolation=cv2.INTER_AREA)

    def glyphs(self, frame, region, min_level=None):
        """Cut out each digit in `region`, left to right. Returns [(image, box)]."""
        area, ox, oy = _crop(frame, region)
        level = min_level or self.MIN_LEVEL
        binary = ((area.min(axis=2) >= level) * 255).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        comps = [stats[i] for i in range(1, n)
                 if stats[i][cv2.CC_STAT_AREA] >= 12 and stats[i][cv2.CC_STAT_WIDTH] >= 4]
        if not comps:
            return []
        median_h = float(np.median([s[cv2.CC_STAT_HEIGHT] for s in comps]))
        median_cy = float(np.median([s[cv2.CC_STAT_TOP] + s[cv2.CC_STAT_HEIGHT] / 2 for s in comps]))
        keep = []
        for l, t, w, h, _ in comps:
            # same height as the other digits and on the same baseline -> a digit, else noise
            if abs(h - median_h) <= 0.25 * median_h and abs(t + h / 2 - median_cy) <= 0.3 * median_h:
                keep.append((l, t, w, h))
        keep.sort()
        return [(self._normalise(binary[t:t + h, l:l + w]), (l + ox, t + oy, w, h)) for l, t, w, h in keep]

    def classify(self, glyph):
        if self._templates is None:
            self._load()
        best, best_score = None, -1.0
        for digit, tpl in self._templates:
            s = float(cv2.matchTemplate(glyph, tpl, cv2.TM_CCOEFF_NORMED)[0][0])
            if s > best_score:
                best, best_score = digit, s
        return best, best_score

    def read(self, frame, region, min_score=0.6, min_level=None):
        """The number in `region`, or None if it could not be read confidently."""
        if not self.ready:
            raise RuntimeError("Digit images missing in assets/digits")
        found = [self.classify(g) for g, _ in self.glyphs(frame, region, min_level)]
        # a weak glyph at either end is usually a speck of background: drop it
        while found and found[0][1] < min_score:
            found.pop(0)
        while found and found[-1][1] < min_score:
            found.pop()
        if not found or any(s < min_score for _, s in found) or any(d == "/" for d, _ in found):
            return None
        return int("".join(d for d, _ in found))


digits = DigitReader()


# --- text OCR (account names, recipe names) --------------------------------------------

class TextReader:
    """RapidOCR (PaddleOCR models on ONNX Runtime). Loaded on first use."""

    def __init__(self):
        self._engine = None
        self._lock = threading.Lock()

    def _get(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self._engine = RapidOCR()
        return self._engine

    def read(self, frame, region=None):
        """Find and read all text in `region`. Returns [(text, score, (x, y, w, h))] in game space."""
        area, ox, oy = _crop(frame, region)
        if area.shape[0] < 8 or area.shape[1] < 8:
            return []
        with self._lock:
            result, _ = self._get()(area)
        out = []
        for pts, text, conf in result or []:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            x, y = int(min(xs)) + ox, int(min(ys)) + oy
            out.append((text, float(conf), (x, y, int(max(xs) - min(xs)), int(max(ys) - min(ys)))))
        return out

    def read_line(self, frame, region):
        """Read a single known line of text (no detection step: faster)."""
        area, _, _ = _crop(frame, region)
        if area.shape[0] < 8 or area.shape[1] < 8:
            return "", 0.0
        with self._lock:
            result, _ = self._get()(area, use_det=False, use_cls=False, use_rec=True)
        if not result:
            return "", 0.0
        text, conf = result[0][0], result[0][1]
        return text, float(conf)


text_reader = TextReader()
