"""Deploying an army with an attack plan, then ending the battle.

Plans live in config/attack_plans.json. A step selects a unit by its troop-bar slot number (the
card is tapped: BlueStacks shows no keyboard keys on the cards) and drops it at a list of points.
A step's "key" is only its name (1, 2, 3 troops, z siege, q/w/e/r heroes, a/s/d spells).

Smart deployment (loot settings):
  * count_troops - read the count on the card (x15) and tap exactly that many
    times, checking after each tap that one unit really came out. A tap that
    did not deploy (illegal spot) moves that spot and tries again. Stops the
    moment the card is empty, so no unit is dropped by accident.
  * smart_deploy - instead of fixed points, drop troops on a ring just outside
    the scouted base's buildings (see deployzone.py). Heroes go to the ring point
    nearest the plan's hero spot. Spells always use the plan's points.
  * afterwards any troop still left on the bar is dropped on the ring.
  * "style": "clone_groups" (edrag_clone) - the dragons go down in 3 tight groups (left, top,
    right), and a Clone is cast on each group as it lands.
"""

import copy
import json
import logging
import math
import os
import re
import time

import cv2
import numpy as np

from . import deployzone, paths, vision
from .control import control
from .space import space
from .states import detect, surrender

log = logging.getLogger("bot")

PLANS_PATH = os.path.join(paths.CONFIG, "attack_plans.json")

# The old bot's E-Dragon attack.
DEFAULT_PLANS = {
    "edrag_spread": {
        "description": "Spells on 3 sides, E-Dragons + Lava + Baby all round, heroes on 4 sides, siege last",
        "offsets": [[-15, -15], [0, 0], [15, 15]],
        "points": {
            "spells": [[240, 525], [913, 10], [1708, 520]],
            "ring": [[683, 876], [491, 714], [240, 525], [515, 312], [751, 137], [913, 10],
                     [1177, 125], [1438, 306], [1708, 520], [1539, 675], [1298, 848]],
            "king": [[491, 714]],
            "queen": [[751, 137]],
            "warden": [[1438, 306]],
            "champion": [[1298, 848]],
        },
        "steps": [
            {"key": "a", "slot": 9, "points": "spells", "type": "spell"},
            {"key": "3", "slot": 3, "points": "ring", "type": "troop"},
            {"key": "1", "slot": 1, "points": "ring", "type": "troop"},
            {"key": "2", "slot": 2, "points": "ring", "type": "troop"},
            {"key": "q", "slot": 5, "points": "king", "type": "hero"},
            {"key": "w", "slot": 6, "points": "queen", "type": "hero"},
            {"key": "e", "slot": 7, "points": "warden", "type": "hero"},
            {"key": "r", "slot": 8, "points": "champion", "type": "hero"},
            {"key": "z", "slot": 4, "points": "ring", "type": "siege"},
        ],
    }
}


def load_plans():
    if not os.path.exists(PLANS_PATH):
        with open(PLANS_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_PLANS, f, indent=2)
    with open(PLANS_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_plan(name):
    plans = load_plans()
    if name not in plans:
        log.warning("Attack plan '%s' not found; using edrag_spread", name)
        return copy.deepcopy(DEFAULT_PLANS["edrag_spread"])
    return plans[name]


def step_type(step):
    if step.get("type"):
        return step["type"]
    k = (step.get("key") or "").lower()
    if k in ("q", "w", "e", "r"):
        return "hero"
    if k in ("a", "s", "d", "f", "g"):
        return "spell"
    if k in ("z", "x"):
        return "siege"
    return "troop"


# --- troop bar ------------------------------------------------------------------------

def detect_slots(frame, region=None):
    """X centres of the troop-bar cards, left to right (cards are ~108 px wide)."""
    x, y, w, h = region or (0, frame.shape[0] - space.s(140), frame.shape[1], space.s(120))
    gray = cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY).astype(np.float32)
    edge = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)) > 60
    cols = np.where(edge.mean(axis=0) > 0.6)[0]
    borders = []
    for c in cols:
        if borders and c - borders[-1][-1] <= 3:
            borders[-1].append(c)
        else:
            borders.append([c])
    borders = [int(np.mean(b)) for b in borders]
    cards, i = [], 0
    while i < len(borders):
        a = borders[i]
        pair = next((j for j in range(i + 1, len(borders))
                     if space.s(98) <= borders[j] - a <= space.s(120)), None)
        if pair is None:
            i += 1
            continue
        cards.append(x + (a + borders[pair]) // 2)
        i = pair + 1
    return cards


def _card_y():
    return space.point(0, 1000)[1]


def read_count(frame, cx):
    """The 'x15' count on the card centred at cx, or None (heroes/sieges have none, empty is grey).
    The selected card is raised a few pixels, so both label positions are read and the
    longer number wins."""
    best = None
    for top in (924, 915):                  # the "x15" is right of the card's middle (a hero's pet icon is left)
        v = vision.digits.read(frame, (cx + space.s(2), space.point(0, top)[1], space.s(56), space.s(32)))
        if v is not None and (best is None or len(str(v)) > len(str(best))):
            best = v
    if best is None:            # the selected card is lighter: the game-font reader misses its white digits
        text, conf = vision.text_reader.read_line(frame, (cx - space.s(12), space.point(0, 915)[1], space.s(70),
                                                          space.s(34)))
        m = re.match(r"\s*[x×]\s*(\d{1,3})\s*$", text.lower())
        if m and conf > 0.6:
            best = int(m.group(1))
    return best


def slot_empty(frame, cx):
    """Used-up cards turn grey."""
    y = space.point(0, 960)[1]
    card = frame[y:y + space.s(70), max(0, cx - space.s(45)):cx + space.s(45)]
    return cv2.cvtColor(card, cv2.COLOR_BGR2HSV)[:, :, 1].mean() < 25


def _card(frame, cx):
    y = space.point(0, 925)[1]
    return frame[y:y + space.s(130), max(0, cx - space.s(50)):cx + space.s(50)].astype(np.int16)


def select(bot, step, slots):
    """Select the unit for a step: tap its card on the troop bar."""
    n = step.get("slot")
    if n and 1 <= n <= len(slots):
        bot.tap(slots[n - 1], _card_y(), jitter=4)
        return True
    log.warning("Step %s: slot %s not on the troop bar", step, n)
    return False


# --- placing ----------------------------------------------------------------------------

def _spread(points, n):
    """n points picked evenly around a list (cycling if n > len)."""
    if not points or n <= 0:
        return []
    if n >= len(points):
        return [points[i % len(points)] for i in range(n)]
    return [points[int(i * len(points) / n)] for i in range(n)]


def _nudge(pt, centre, outward=True, step=34):
    """Move a point away from (or toward) the base centre."""
    x, y = pt
    dx, dy = x - centre[0], y - centre[1]
    d = math.hypot(dx, dy) or 1.0
    k = step if outward else -step
    return int(x + dx / d * k), int(y + dy / d * k)


def _label(frame, cx):
    y = space.point(0, 910)[1]
    return frame[y:y + space.s(50), max(0, cx - space.s(12)):cx + space.s(54)].astype(np.int16)


def _drop(bot, cx, spots, centre, single=False, fixes=None, reselect=None, count_override=None):
    """Drop every unit on the card at cx, checking that each tap really deployed one.

    Returns True only when the card was observed to change / empty, False if no deployment
    could be confirmed. Counted troop cards are checked by count; single hero/siege cards by
    their card image changing.
    """
    if not spots:
        return False
    fixes = {} if fixes is None else fixes

    def fixed(p):
        seen = 0
        while p is not None and p in fixes and seen < 10:
            p, seen = fixes[p], seen + 1
        return p

    frame = bot.shot()
    wanted = list(spots)
    spots = [p for p in (fixed(p) for p in spots) if p is not None and deployzone.valid_spot(frame, *p)]
    good = fixes.setdefault("__good__", [])
    if not spots and good:
        ref = wanted[0] if wanted else centre
        spots = sorted(set(good), key=lambda g: (g[0] - ref[0]) ** 2 + (g[1] - ref[1]) ** 2)[:max(1, len(wanted))]
    if not spots:
        log.warning("No usable deploy spots left")
        return False
    moves = {}
    count = count_override if count_override is not None else (None if single else read_count(frame, cx))
    by_count = count is not None
    left = count if by_count else 1
    queue = _spread(spots, left)
    tries, max_tries = 0, left * 2 + 10
    while left > 0 and queue and tries < max_tries:
        control.checkpoint()
        tries += 1
        card0, label0 = _card(frame, cx), _label(frame, cx)
        x, y = queue.pop(0)
        bot.tap(x, y, jitter=3)
        ok = False
        waited = 0.0
        for pause in (0.08, 0.1, 0.1, 0.12):
            time.sleep(pause)
            waited += pause
            frame = bot.shot()
            if not single and slot_empty(frame, cx):
                good.append((x, y))
                return True
            if by_count:
                now = read_count(frame, cx)
                if now is not None and now < left:
                    left, ok = now, True
                    break
                if now is None and np.abs(_label(frame, cx) - label0).mean() > 10:
                    left, ok = left - 1, True
                    break
            elif np.abs(_card(frame, cx) - card0).mean() > 12:
                good.append((x, y))
                return True
        if ok:
            good.append((x, y))
        log.debug("tap %s: %s, %s left (%.2fs)", (x, y), "ok" if ok else "no effect", left, waited)
        if not ok:
            n = moves.get((x, y), 0) + 1
            nx, ny = _nudge((x, y), centre, outward=deployzone.in_diamond(x, y, inset=-deployzone.MAP_GROW))
            if n <= 3 and deployzone.valid_spot(frame, nx, ny):
                fixes[(x, y)] = (nx, ny)
                moves[(nx, ny)] = n
                queue.append((nx, ny))
            else:
                fixes[(x, y)] = None
                spots = [p for p in spots if p != (x, y)]
            if reselect:
                reselect()
        if not queue and left > 0:
            queue = [p for p in (fixed(p) for p in _spread(spots, left)) if p is not None]
    return left <= 0


CLONE_IN = 55          # a Clone goes this far inside a dragon group's spot: where the dragons fly to
GROUP_SPREAD = 15      # the units of a group land within this many pixels of its spot (the old bot's offsets)


def clone_card(frame, slots):
    """X of the Clone spell's card on the troop bar (found by its picture), or None."""
    if not vision.templates.has("battle/clone_card"):
        return None
    ms = [m for m in vision.find_all(frame, "battle/clone_card") if not slot_empty(frame, m.x)]
    if not ms:
        return None
    m = max(ms, key=lambda m: m.score)
    return min(slots, key=lambda c: abs(c - m.x)) if slots else m.x


def _sides(plan, ring, centre):
    """The spots of the dragon groups: the plan's spell spots (left, top and right of the map, like
    the old bot), each moved to the nearest point of the deploy ring when the ring was found."""
    pts = [space.center(x, y) for x, y in plan["points"].get("spells", [])] or \
        [space.center(240, 525), space.center(913, 10), space.center(1708, 520)]
    if not ring:
        return pts
    return [min(ring, key=lambda r: (r[0] - p[0]) ** 2 + (r[1] - p[1]) ** 2) for p in pts]


def _toward(pt, centre, d):
    x, y = pt
    dx, dy = centre[0] - x, centre[1] - y
    n = math.hypot(dx, dy) or 1.0
    return int(x + dx / n * d), int(y + dy / n * d)


def no_card(frame, cx):
    """An empty slot of the troop bar (a dashed outline over the battlefield): the top-left corner of a card is its
    bright frame (or a hero's picture), an empty slot shows the darker battlefield."""
    y = space.point(0, 928)[1]
    corner = cv2.cvtColor(frame[y:y + space.s(12), max(0, cx - space.s(45)):cx - space.s(25)], cv2.COLOR_BGR2HSV)
    return corner.size == 0 or float(corner[:, :, 2].mean()) < 150


def bar_count(frame, cx):
    """The "x11" on a troop or spell card (0 = used up), or None - a siege machine or a hero has none. Read as text
    and only taken with its "x": a hero's picture or pet icon can look like a digit."""
    for top in (915, 924):
        text, _ = vision.text_reader.read_line(frame, (cx - space.s(12), space.point(0, top)[1], space.s(70),
                                                       space.s(34)))
        m = re.fullmatch(r"\s*[x×]\s*([0-9oO]{1,3})\s*", text.lower())
        if m:
            return int(m.group(1).replace("o", "0"))
    return None


def bar_cards(frame, slots):
    """Read the live troop bar: counted troops, uncounted siege/heroes, then spells.

    Spell counts can be read even when later spell-card counts fail OCR. The first counted
    card after the first uncounted card marks the start of the spell section; keep every
    subsequent card in that section as a spell, including cards whose count OCR failed.
    """
    cards = []
    scanned = []
    for cx in slots:
        n = bar_count(frame, cx)
        blank = no_card(frame, cx)
        grey = slot_empty(frame, cx)
        if n == 0:
            scanned.append(f"{cx}: used-up x0")
            continue
        if n is None and blank and grey:
            scanned.append(f"{cx}: blank")
            continue
        cards.append((cx, n))
        scanned.append(f"{cx}: {'single' if n is None else 'x' + str(n)} "
                       f"(corner_blank={blank}, grey={grey})")

    first_single = next((i for i, (_, n) in enumerate(cards) if n is None), None)
    spell_start = None
    if first_single is not None:
        spell_start = next((i for i in range(first_single + 1, len(cards))
                            if cards[i][1] is not None), None)

    if first_single is None:
        troops = [c for c in cards if c[1] is not None]
        singles, spells = [], []
    elif spell_start is None:
        troops = [c for c in cards[:first_single] if c[1] is not None]
        singles = [cx for cx, n in cards[first_single:] if n is None]
        spells = []
    else:
        troops = [c for c in cards[:first_single] if c[1] is not None]
        singles = [cx for cx, n in cards[first_single:spell_start] if n is None]
        # Preserve later cards even if their count could not be read. _drop will verify them
        # by count where possible, otherwise by a card-image change.
        spells = [(cx, n) for cx, n in cards[spell_start:]]

    log.info("Troop bar scan (%d candidate slots): %s", len(slots), ", ".join(scanned) or "none")
    log.info("Troop bar sections: %d troop(s), %d single(s), %d spell card(s)",
             len(troops), len(singles), len(spells))
    return troops, singles, spells


def _pick(bot, cx):
    """Select the card at x on the troop bar."""
    bot.tap(cx, _card_y(), jitter=4)
    return True


def _cast_one_spell(bot, cx, point, label):
    """Cast one spell at a point and confirm the troop-bar count actually decreases."""
    _pick(bot, cx)
    time.sleep(0.08)
    before_frame = bot.shot()
    before = read_count(before_frame, cx)
    if before is None:
        before = bar_count(before_frame, cx)
    card_before = _card(before_frame, cx)
    bot.tap(*point, jitter=2)

    after = None
    for pause in (0.12, 0.16, 0.2, 0.25):
        time.sleep(pause)
        frame = bot.shot()
        if slot_empty(frame, cx):
            log.info("%s spell at %s confirmed (card used up)", label, point)
            return True
        after = read_count(frame, cx)
        if after is None:
            after = bar_count(frame, cx)
        if before is not None and after is not None and after < before:
            log.info("%s spell at %s confirmed (%s -> %s)", label, point, before, after)
            return True
        if before is None and after is None and np.abs(_card(frame, cx) - card_before).mean() > 12:
            log.info("%s spell at %s card changed; deployment likely", label, point)
            return True

    log.warning("%s spell at %s was NOT confirmed (count %s -> %s)",
                label, point, before, after)
    return False


def deploy_clone_groups(bot, plan, frame, slots, ring, centre, fixes):
    """Deploy counted troops in groups, then siege/heroes, then non-Clone spells."""
    troops, singles, spells = bar_cards(frame, slots)
    clone_x = clone_card(frame, slots)
    troops = [t for t in troops if t[0] != clone_x]
    spells = [t for t in spells if t[0] != clone_x]
    clones = (read_count(frame, clone_x) or 1) if clone_x is not None else 0
    sides = _sides(plan, ring, centre)
    groups = []
    for cx, n in troops:
        k = len(sides)
        for i, spot in enumerate(sides):
            share = n // k + (1 if i < n % k else 0)
            if share:
                groups.append((spot, cx, share))
    log.info("Troop bar: %d troop card(s), %d siege machine / hero card(s), %d other spell card(s)%s. "
             "Deploying %d group(s) on %d side(s)", len(troops), len(singles), len(spells),
             f", {clones} Clone spell(s)" if clone_x is not None else ", no Clone spell",
             len(groups), len(sides))

    cast = 0
    good = []
    for preferred, cx, n in groups:
        control.checkpoint()
        _pick(bot, cx)
        spot = _land_with_fallback(bot, cx, preferred, centre, ring)
        if spot is None:
            log.info("No usable spot near %s: its %d unit(s) remain for the later ring drop", preferred, n)
            continue
        good.append(spot)
        tx, ty = centre[1] - spot[1], spot[0] - centre[0]
        d = math.hypot(tx, ty) or 1.0
        for i in range(1, n):
            k = ((i + 1) // 2) * (1 if i % 2 else -1) * space.f(GROUP_SPREAD)
            bot.tap(int(spot[0] + tx / d * k), int(spot[1] + ty / d * k), jitter=2)
            time.sleep(0.07)
        if clone_x is not None and cast < clones:
            time.sleep(0.15)
            if _cast_one_spell(bot, clone_x, spot, f"Clone {cast + 1}/{clones}"):
                cast += 1

    # If there are more Clone spells than successful groups, reuse only confirmed troop locations.
    while clone_x is not None and cast < clones and good:
        spot = good[cast % len(good)]
        if _cast_one_spell(bot, clone_x, spot, f"Clone {cast + 1}/{clones}"):
            cast += 1
        else:
            break

    bot.deploy_spots = good
    behind = good or sides

    # Deploy the siege machine and every available hero. If the preferred point fails, _drop
    # advances through nearby points on the ring rather than giving up on that hero.
    for i, cx in enumerate(singles):
        control.checkpoint()
        current = bot.shot()
        if no_card(current, cx) and slot_empty(current, cx):
            log.debug("Skipping genuinely blank single-card slot at %d", cx)
            continue
        _pick(bot, cx)
        preferred = behind[i % len(behind)]
        candidates = ring or sides
        alternatives = sorted(
            (p for p in candidates if p != preferred),
            key=lambda p: (p[0] - preferred[0]) ** 2 + (p[1] - preferred[1]) ** 2,
        )
        deployed = _drop(bot, cx, [preferred] + alternatives, centre, single=True, fixes=fixes,
                          reselect=lambda x=cx: _pick(bot, x))
        if deployed:
            log.info("Single siege / hero card at %d deployed", cx)
        else:
            log.warning("Could not confirm deployment for single siege / hero card at %d", cx)
        time.sleep(0.1)
    log.info("Attempted deployment for %d siege machine / hero card(s) across %d candidate spot(s)",
             len(singles), len(ring or sides))

    # Other spells are dropped just inside the successful troop groups.
    for cx, n in spells:
        control.checkpoint()
        frame = bot.shot()
        count = read_count(frame, cx)
        if count is None:
            count = bar_count(frame, cx)
        if count == 0:
            log.info("Skipping used-up spell card at %d", cx)
            continue

        spots = [_toward(p, centre, space.f(CLONE_IN + 60)) for p in behind]
        _pick(bot, cx)  # select the spell before its first battlefield tap
        deployed = _drop(bot, cx, spots, centre, fixes=fixes, count_override=count,
                         reselect=lambda x=cx: _pick(bot, x))
        if deployed:
            log.info("Spell card at %d deployed", cx)
        else:
            log.warning("Spell card at %d was not confirmed; check troop-bar count / screenshot", cx)
    return [cx for cx, _ in troops]


def _land_with_fallback(bot, cx, spot, centre, ring, alternatives=5):
    """Try the preferred side first, then nearby points on the detected deploy line."""
    candidates = [spot]
    if ring:
        nearby = sorted(
            (p for p in ring if p != spot),
            key=lambda p: (p[0] - spot[0]) ** 2 + (p[1] - spot[1]) ** 2,
        )
        candidates.extend(nearby[:alternatives])
    for candidate in candidates:
        landed = _land(bot, cx, candidate, centre)
        if landed is not None:
            return landed
    return None


def _land(bot, cx, spot, centre, tries=4):
    """Drop one unit of the selected card at `spot`; if it does not come out (red area, off the map),
    the spot moves out (or in) and is tried again. Returns the spot that worked, or None."""
    frame = bot.shot()
    before = read_count(frame, cx)
    p = spot
    for _ in range(tries):
        if deployzone.valid_spot(frame, *p):
            bot.tap(*p, jitter=1)
            for pause in (0.1, 0.12, 0.15):
                time.sleep(pause)
                frame = bot.shot()
                now = read_count(frame, cx)
                if slot_empty(frame, cx) or (before is not None and now is not None and now < before):
                    return p
                if before is None and now is not None:
                    return p                          # (count not read before: it changed)
            log.debug("deploy spot %s: nothing came out", p)
        outward = deployzone.in_diamond(p[0], p[1], inset=-deployzone.MAP_GROW)
        p = _nudge(p, centre, outward=outward, step=space.f(40))
    return None


SPEED_BUTTON_SCALES = [
    0.75, 0.775, 0.80, 0.825, 0.85, 0.875, 0.90, 0.925, 0.95, 0.975,
    1.00, 1.025, 1.05, 1.075, 1.10, 1.125, 1.15, 1.175, 1.20,
]
SPEED_BUTTON_THRESHOLD = 0.82


def _find_speed_button(frame, key):
    """Find a speed-button template across emulator UI scales in the fixed lower-right region."""
    match, scale = vision.find_scaled(
        frame, key, scales=SPEED_BUTTON_SCALES, threshold=0.0
    )
    if not match:
        log.debug("Speed button %s had no template match", key)
        return None
    log.debug("Speed button %s best match %.3f (scale %.3f)", key, match.score, scale)
    return match if match.score >= SPEED_BUTTON_THRESHOLD else None


def ensure_four_x(bot, timeout=2.5):
    """Enable 4x battle speed when the battle button is visibly at 1x.

    Search a range of image scales because BlueStacks / Google Play Games can
    produce different game-space sizes. Unknown states are left untouched.
    """
    speed_1x = "battle/speed_1x"
    speed_4x = "battle/speed_4x"
    frame = bot.shot()
    four = _find_speed_button(frame, speed_4x)
    if four:
        log.info("Battle speed already at 4x")
        return True

    one = _find_speed_button(frame, speed_1x)
    if not one:
        log.warning("Battle speed button not recognized as 1x or 4x; leaving it unchanged")
        bot.save_error("speed-button-unrecognized", frame)
        return False

    log.info("Battle speed is 1x; switching to 4x")
    bot.tap_match(one, jitter=0)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        control.sleep(0.15)
        frame = bot.shot()
        if _find_speed_button(frame, speed_4x):
            log.info("Battle speed switched to 4x (verified)")
            return True

    log.warning("4x speed was not confirmed after the tap; continuing without tapping again")
    return False

def deploy(bot, plan):
    # Start the battle clock before the speed toggle so its verification time counts too.
    bot.deploy_started = time.monotonic()
    ensure_four_x(bot)

    s = bot.settings["loot"]
    smart, verify = s.get("smart_deploy", True), s.get("count_troops", True)
    offsets = plan.get("offsets") or [[0, 0]]
    frame = bot.shot()
    slots = detect_slots(frame)

    def card_of(step):
        """X of the card a step uses, by its slot number."""
        n = step.get("slot")
        return slots[n - 1] if n and n <= len(slots) else None

    ring = deployzone.deploy_line(frame) if smart else []
    if smart and len(ring) < 8:
        log.info("Deploy zone not found (%d points); using the plan's points", len(ring))
        bot.save_error("no-deploy-zone")
        ring = []
    if ring:
        centre = (int(np.mean([p[0] for p in ring])), int(np.mean([p[1] for p in ring])))
    else:
        centre = space.center(deployzone.DIAMOND["cx"], deployzone.DIAMOND["cy"])

    def plan_points(step):
        pts = plan["points"].get(step["points"], []) if isinstance(step["points"], str) else step["points"]
        return [space.center(x, y) for x, y in pts]

    def nearest_on_ring(pt):
        return min(ring, key=lambda r: (r[0] - pt[0]) ** 2 + (r[1] - pt[1]) ** 2)

    fixes = {}                                  # bad spot -> corrected spot, shared by all units
    bot.deploy_spots = []
    if plan.get("style") == "clone_groups" and verify:
        troops = deploy_clone_groups(bot, plan, frame, slots, ring, centre, fixes)
        frame = bot.shot()                      # the troops left over: on the ring where the others landed
        for cx in troops:
            if not slot_empty(frame, cx) and read_count(frame, cx) and _pick(bot, cx):
                log.debug("Dropping leftovers of the card at %d", cx)
                _drop(bot, cx, getattr(bot, "deploy_spots", None) or ring, centre, fixes=fixes,
                      reselect=lambda x=cx: _pick(bot, x))
                frame = bot.shot()
        return
    for step in plan["steps"]:
        control.checkpoint()
        kind = step_type(step)
        cx = card_of(step)
        if cx is not None and slot_empty(bot.shot(), cx):
            continue                         # nothing of this unit left
        if not select(bot, step, slots):
            continue
        base_pts = plan_points(step) if isinstance(step.get("points"), list) or step.get("points") in plan["points"] else []
        if kind == "spell" and step.get("points") == "ring":
            # e.g. Clone right after the dragons: just inside the ring, spread around the base
            src = ring or base_pts
            spots = [(int(x + (centre[0] - x) * 0.18), int(y + (centre[1] - y) * 0.18)) for x, y in src]
        elif kind == "spell" or not ring:
            spots = base_pts
        elif step.get("points") == "ring" and kind != "hero":
            spots = ring
        else:
            spots = [nearest_on_ring(p) for p in base_pts]
        if cx is None or not verify:
            for dx, dy in step.get("offsets", offsets):   # the old way: each point once per offset
                for px, py in spots:
                    bot.tap(px + dx, py + dy, jitter=2)
        else:
            _drop(bot, cx, spots, centre, single=kind in ("hero", "siege"), fixes=fixes,
                  reselect=lambda st=step: select(bot, st, slots))
        time.sleep(0.1)

    # any troop of the plan still showing a count on the bar -> drop the rest on the ring
    if verify and slots:
        frame = bot.shot()
        for step in plan["steps"]:
            cx = card_of(step)
            if step_type(step) != "troop" or cx is None:
                continue
            if not slot_empty(frame, cx) and read_count(frame, cx) and select(bot, step, slots):
                log.debug("Dropping leftovers of slot %s", step.get("slot"))
                _drop(bot, cx, getattr(bot, "deploy_spots", None) or ring or plan_points(step), centre,
                      fixes=fixes, reselect=lambda st=step: select(bot, st, slots))
                frame = bot.shot()


def _results(frame):
    """The battle results are showing (cheaper than detect() while the battle runs)."""
    return any(vision.templates.has(k) and vision.find(frame, k)
               for k in ("results/return_home", "results/claim_reward"))


def finish_battle(bot, seconds, started=None, stall=0, watch=("gold", "elixir", "dark")):
    """The battle lasts at most `seconds` from `started` (when the attack began; default now), and - with
    `stall` - ends as soon as none of the loot left in the base ("Available Loot", top left: gold, elixir and
    dark elixir) has gone down for `stall` seconds after it started going down (the troops are dead or stuck far
    from the storages). Any of them going down counts: troops busy on gold mines are still looting. It is
    surrendered then, retrying until the results show (a single missed Surrender let battles run to the game's
    3 minutes). Returns True once the results screen is showing."""
    end = (time.monotonic() if started is None else started) + seconds
    left, moved = {}, None                # the loot left in the base, and when it last went down
    while time.monotonic() < end:
        frame = bot.shot()
        if _results(frame):
            return True
        if stall:
            for r in watch:
                v = vision.digits.read(frame, bot.layout.region(f"scout.{r}"))
                if v is None:
                    continue                  # (unread this time: the others still count)
                if r in left and v < left[r]:
                    moved = time.monotonic()
                if r not in left or v <= left[r]:
                    left[r] = v               # (a misread higher number is ignored)
            if moved and time.monotonic() - moved >= stall:
                log.info("No more loot for %d s (%s left): ending the battle", stall,
                         ", ".join(f"{r} {v:,}" for r, v in left.items()))
                break
        control.sleep(0.5)
    give_up = time.monotonic() + 25
    tries = 0
    while time.monotonic() < give_up:
        frame = bot.shot()
        state = detect(frame)
        if state == "results":
            return True
        if state in ("battle", "unknown", "confirm"):
            if state == "confirm":
                bot.tap_template("battle/confirm_okay", timeout=1)
            elif not surrender(bot, frame, blind=tries >= 2):
                if tries == 1:
                    bot.save_error("no-surrender")     # what is covering the Surrender button
                tries += 1
        control.sleep(0.7)
    log.warning("The battle could not be ended after %d s", seconds)
    return False
