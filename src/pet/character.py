"""蹇冩湀鐙?(Hsin / Moon Fox) 鈥?procedural character art.

The character is composed from anti-aliased vector primitives and rendered as
three parallax layers (back group / body / head) so the sprite builder can add
breathing squash, head tilt and tail sway between frames.

Palette follows the Moon Fox read: silver-ivory hair, moon-violet eyes,
indigo-and-gold celestial robe, nine luminous tails, crescent-moon hairpin.
"""
from __future__ import annotations

import math

import numpy as np

from .vector import Canvas

# --------------------------------------------------------------------- palette
HAIR = (242, 245, 252)
HAIR_MID = (214, 224, 245)
HAIR_DEEP = (176, 192, 224)
HAIR_SHADE = (146, 164, 205)
HAIR_LINE = (108, 128, 176)

SKIN = (255, 240, 234)
SKIN_SHADE = (247, 213, 208)
SKIN_LINE = (198, 142, 146)

ROBE = (58, 61, 114)
ROBE_DEEP = (39, 41, 84)
ROBE_LIGHT = (86, 92, 158)
ROBE_LINE = (28, 29, 62)
GOLD = (247, 205, 106)
GOLD_DEEP = (204, 154, 54)
TEAL = (124, 236, 226)
MOON = (168, 216, 255)
MOON_PALE = (226, 241, 255)

EYE_DEEP = (74, 48, 116)
EYE_IRIS = (140, 108, 214)
EYE_LIGHT = (196, 174, 248)
EYE_PUPIL = (38, 24, 62)
WHITE = (255, 255, 255)
BLUSH = (255, 158, 178)
LINE = (64, 58, 96)

OUTLINE = (86, 82, 126)
OUTLINE_SOFT = (86, 82, 126)
# Tail separation uses a light edge: a dark soft edge is invisible at low alpha,
# but a colour-keyed (1-bit) window would still paint it and look dirty.
TAIL_EDGE = (176, 194, 232)


def rgba(color, a=255):
    return (color[0], color[1], color[2], int(a))


def mix(c1, c2, t):
    return tuple(int(round(c1[i] + (c2[i] - c1[i]) * t)) for i in range(3))


# ----------------------------------------------------------------- canvas size
W, H = 232.0, 248.0
CX = W / 2.0
GROUND_Y = 218.0

TAIL_BASE = (CX, 168.0)
HEAD_C = (CX, 92.0)
HEAD_R = 45.0

# tail fan defaults (tunable via set_tail_style)
TAIL_COUNT = 9
TAIL_BASE_DY = 0.0
TAIL_SPREAD = 70.0
TAIL_LEN = 84.0
TAIL_EXTRA = 32.0
TAIL_CURL = 40.0
TAIL_W = 15.0


def _tail_dir(angle_deg, swing):
    a = math.radians(angle_deg + swing)
    return math.cos(a), math.sin(a)


def set_tail_style(count=None, base_dy=None, spread=None, length=None, extra=None,
                   curl=None, width=None):
    """Override tail geometry (used by the design sweep and by skins)."""
    global TAIL_COUNT, TAIL_BASE_DY, TAIL_SPREAD, TAIL_LEN, TAIL_EXTRA, TAIL_CURL, TAIL_W
    if count is not None:
        TAIL_COUNT = int(count)
    if base_dy is not None:
        TAIL_BASE_DY = float(base_dy)
    if spread is not None:
        TAIL_SPREAD = float(spread)
    if length is not None:
        TAIL_LEN = float(length)
    if extra is not None:
        TAIL_EXTRA = float(extra)
    if curl is not None:
        TAIL_CURL = float(curl)
    if width is not None:
        TAIL_W = float(width)


def draw_tails(c: Canvas, swing=0.0, spread=1.0, glow=0.5):
    """Nine luminous tails arching up and out behind the character."""
    n = max(3, TAIL_COUNT)
    base_y = TAIL_BASE[1] + TAIL_BASE_DY
    for i in range(n):
        t = i / (n - 1.0)
        # 0 deg = straight up, positive = to the right
        angle = -TAIL_SPREAD + 2.0 * TAIL_SPREAD * t
        # middle tails longest, outer ones shorter
        length = (TAIL_LEN + TAIL_EXTRA * math.sin(math.pi * (0.14 + 0.72 * t))) * spread
        # bend outward so the fan arcs like fur rather than radiating as spokes
        curl = (t - 0.5) * 2.0 * TAIL_CURL
        sway = swing * (0.6 + 0.7 * t)

        pts = []
        steps = 18
        for s in range(steps + 1):
            u = s / steps
            ang = math.radians(angle + curl * u * u + sway * u * 1.2)
            r = length * u
            wobble = math.sin(u * 3.2 + t * 5.0) * 2.0 * u
            x = TAIL_BASE[0] + math.sin(ang) * (r + wobble)
            y = base_y - math.cos(ang) * (r + wobble)
            pts.append((x, y))

        width0 = TAIL_W - 2.4 * abs(t - 0.5) * 2
        for s in range(steps):
            u0, u1 = s / steps, (s + 1) / steps
            w0 = width0 * (1.0 - 0.80 * u0) + 1.8
            w1 = width0 * (1.0 - 0.80 * u1) + 1.8
            # near-white at the base, luminous pale moon-blue at the tip
            col = mix(HAIR, mix(MOON_PALE, MOON, 0.28), min(1.0, u1 * 1.45))
            c.capsule(pts[s], pts[s + 1], w1 + 0.9, rgba(TAIL_EDGE, 255),
                      r1=w1 * 0.9 + 0.9, soft=0.4)
            c.capsule(pts[s], pts[s + 1], w0, rgba(col, 255), r1=w1)
            if s == 0:
                c.circle(pts[0][0], pts[0][1], w0 * 0.96, rgba(HAIR, 255), soft=1.0)
        # luminous tip
        tip = pts[-1]
        c.circle(tip[0], tip[1], 5.4, rgba(MOON_PALE, 200), soft=3.0)
        c.circle(tip[0], tip[1], 2.8, rgba(WHITE, 235), soft=1.2)
        # soft fur streak inside the tail
        inner = pts[max(1, int(steps * 0.26))]
        c.circle(inner[0], inner[1], width0 * 0.34, rgba(WHITE, 105), soft=1.8)


def draw_body(c: Canvas, squash=1.0, arm_lift=0.0):
    """Robe, sleeves, hands, chest ornament, ribbon."""
    sy = squash
    sx = 1.0 / math.sqrt(max(sy, 1e-3))

    def P(x, y):  # apply squash about the ground line
        return (CX + (x - CX) * sx, 218.0 - (218.0 - y) * sy)

    shoulder_y = 150.0
    hem_y = 214.0
    # robe silhouette
    body_pts = [
        P(90, shoulder_y + 4), P(85, 168), P(80, 192), P(76, hem_y),
        P(156, hem_y), P(152, 192), P(147, 168), P(142, shoulder_y + 4),
        P(130, shoulder_y - 3), P(102, shoulder_y - 3),
    ]
    c.polygon(body_pts, rgba(OUTLINE, 255), soft=0.6)
    inner = [
        P(92, shoulder_y + 5), P(87, 168), P(83, 192), P(80, hem_y - 3),
        P(152, hem_y - 3), P(149, 192), P(145, 168), P(140, shoulder_y + 5),
        P(129, shoulder_y - 1), P(103, shoulder_y - 1),
    ]
    c.polygon(inner, rgba(ROBE, 255), soft=0.4)
    # robe gradient: darker toward the hem
    c.polygon([P(76, 188), P(156, 188), P(156, hem_y), P(76, hem_y)],
              rgba(ROBE_DEEP, 120), soft=1.4)
    # sleeve-cape over the shoulders
    c.polygon([P(88, shoulder_y - 2), P(82, 172), P(96, 178), P(106, shoulder_y - 6)],
              rgba(ROBE_LIGHT, 255), soft=0.5)
    c.polygon([P(144, shoulder_y - 2), P(150, 172), P(136, 178), P(126, shoulder_y - 6)],
              rgba(ROBE_LIGHT, 255), soft=0.5)
    # long sleeves + hands
    for side in (-1, 1):
        sx0 = CX + side * 26
        hx = CX + side * (29 + 3 * arm_lift)
        hy = 188 - 10 * arm_lift
        p0 = P(sx0, 158)
        p1 = P(hx, hy)
        c.capsule(p0, p1, 10.0, rgba(OUTLINE, 255), r1=6.6, soft=0.5)
        c.capsule(p0, p1, 8.6, rgba(ROBE_LIGHT, 255), r1=5.2)
        hand = P(hx, hy + 5.0)
        c.circle(hand[0], hand[1], 4.8, rgba(OUTLINE, 255), soft=0.5)
        c.circle(hand[0], hand[1], 3.8, rgba(SKIN, 255))
        c.circle(hand[0] - 1.4 * side, hand[1] - 1.2, 1.4, rgba(WHITE, 120), soft=0.8)
    # collar fur
    c.ellipse(CX, shoulder_y - 1, 21, 9.5, rgba(OUTLINE, 255), soft=0.6)
    c.ellipse(CX, shoulder_y - 2, 19, 8.0, rgba(HAIR, 255))
    c.ellipse(CX, shoulder_y - 3.5, 14, 4.6, rgba(WHITE, 210), soft=1.0)
    # chest ornament: crescent over a teal gem
    cy0 = 170.0
    c.circle(CX, cy0 + 6, 7.0, rgba(MOON, 70), soft=3.6)
    c.crescent(CX, cy0, 7.6, rgba(GOLD, 255), bite=0.62, bite_dy=-0.30, bite_dx=0.42, soft=0.5)
    c.crescent(CX, cy0, 6.2, rgba(GOLD_DEEP, 120), bite=0.62, bite_dy=-0.30, bite_dx=0.42, soft=1.0)
    c.circle(CX, cy0 + 10.5, 3.5, rgba(TEAL, 235), soft=0.9)
    # gold hem trim
    c.capsule(P(77, hem_y - 5), P(155, hem_y - 5), 1.5, rgba(GOLD, 220), r1=1.5, soft=0.6)
    # ribbon streaming out to the right
    for k, off in ((0, 0.0), (1, 2.8)):
        pts = []
        for s in range(11):
            u = s / 10.0
            pts.append(P(146 + 18 * u + off, 178 + 30 * u + math.sin(u * 2.6 + k) * 6.5))
        for s in range(len(pts) - 1):
            w = 3.2 - 1.9 * (s / (len(pts) - 1))
            c.capsule(pts[s], pts[s + 1], w, rgba(GOLD, 210), r1=max(0.8, w - 0.3))
        c.circle(pts[0][0], pts[0][1], 3.2, rgba(GOLD, 235), soft=0.8)


def _eye(c: Canvas, cx, cy, rx, ry, look=0.0, blink=0.0, tilt=-0.10):
    """One anime eye. blink 0..1 closes the lid."""
    open_amt = max(0.0, 1.0 - blink)
    if open_amt < 0.06:
        # closed: a happy curved lash line
        c.capsule((cx - rx, cy), (cx, cy - ry * 0.42), 1.9, rgba(LINE, 255), r1=1.9, soft=0.35)
        c.capsule((cx, cy - ry * 0.42), (cx + rx, cy), 1.9, rgba(LINE, 255), r1=1.9, soft=0.35)
        return
    ry = ry * (0.22 + 0.78 * open_amt)
    # eye white backing
    c.ellipse(cx, cy, rx, ry, rgba(OUTLINE, 255), soft=0.55, rot=tilt)
    c.ellipse(cx, cy + 0.4, rx - 1.15, ry - 1.15, rgba(WHITE, 255), rot=tilt)
    # iris stack
    ix = cx + look * rx * 0.30
    top = cy - ry * 0.62
    bot = cy + ry * 0.80
    steps = 7
    for s in range(steps):
        t0 = s / steps
        yy = top + (bot - top) * (t0 + 0.5 / steps)
        rr = (rx - 1.5) * (1.0 - 0.30 * t0)
        col = mix(EYE_DEEP, EYE_IRIS, 0.35 + 0.65 * t0)
        col = mix(col, EYE_LIGHT, max(0.0, (t0 - 0.55)) * 1.5)
        c.capsule((ix, yy - 1.2), (ix, yy + 1.2), rr, rgba(col, 255), r1=rr * 0.98, soft=0.5)
    # pupil + rim
    c.ellipse(ix, cy + ry * 0.16, rx * 0.36, ry * 0.62, rgba(EYE_PUPIL, 245), soft=0.5)
    c.ellipse(ix, cy + ry * 0.55, rx * 0.52, ry * 0.32, rgba(EYE_LIGHT, 90), soft=0.8)
    # catchlights
    c.circle(ix - rx * 0.34, cy - ry * 0.42, max(1.5, rx * 0.30), rgba(WHITE, 250), soft=0.4)
    c.circle(ix + rx * 0.38, cy + ry * 0.34, max(0.9, rx * 0.17), rgba(WHITE, 190), soft=0.5)
    # upper lash + lid shadow
    c.capsule((cx - rx - 0.6, cy - ry * 0.62), (cx + rx + 0.6, cy - ry * 0.74),
              2.5, rgba(LINE, 255), r1=2.1, soft=0.35)
    c.capsule((cx - rx - 1.8, cy - ry * 0.45), (cx - rx + 0.4, cy - ry * 0.95),
              2.0, rgba(LINE, 255), r1=0.7, soft=0.35)
    # lower lid line (thin)
    c.capsule((cx - rx * 0.85, cy + ry * 0.92), (cx + rx * 0.9, cy + ry * 0.86),
              0.85, rgba(SKIN_LINE, 200), r1=0.85, soft=0.35)


def draw_head(c: Canvas, tilt=0.0, look=0.0, blink_l=0.0, blink_r=0.0, smile=0.0,
              blush=0.0, ear_twitch=0.0):
    """Head layer: hair mass, ears, face, crescent hairpin."""
    hx, hy = HEAD_C

    # --- back hair mass
    c.ellipse(hx, hy + 2, 52, 50, rgba(OUTLINE, 200), soft=0.8)
    c.ellipse(hx, hy, 50.5, 48.5, rgba(HAIR_MID, 255))
    # long side locks falling past the shoulders
    for side in (-1, 1):
        x0 = hx + side * 40
        for k in range(3):
            x = x0 + side * (1.6 * k)
            pts = []
            for s in range(9):
                u = s / 8.0
                px = x + side * (6.0 * math.sin(u * 1.7) + 2.4 * u)
                py = hy + 6 + u * 66
                pts.append((px, py))
            w0 = 10.5 - 1.6 * k
            for s in range(len(pts) - 1):
                w = w0 * (1.0 - 0.38 * (s / (len(pts) - 1)))
                col = mix(HAIR, HAIR_DEEP, 0.18 + 0.50 * (s / (len(pts) - 1)))
                c.capsule(pts[s], pts[s + 1], w + 0.9, rgba(OUTLINE, 110), r1=w * 0.9, soft=0.5)
                c.capsule(pts[s], pts[s + 1], w, rgba(col, 255), r1=max(0.5, w * 0.86))
            tip = pts[-1]
            c.circle(tip[0], tip[1], 3.0, rgba(HAIR_DEEP, 230), soft=1.2)

    # --- fox ears
    for side in (-1, 1):
        tw = ear_twitch * (1 if side < 0 else -1)
        base = (hx + side * 25.0, hy - 32.0)
        tipx = hx + side * (46.0 + tw * 2.0)
        tipy = hy - 80.0 - tw * 3.0
        midx = hx + side * (40.0 + tw * 0.8)
        midy = hy - 58.0
        outer = [base, (midx, midy), (tipx, tipy), (hx + side * 15.0, hy - 42.0)]
        c.polygon(outer, rgba(OUTLINE, 255), soft=0.6)
        inner = [
            (base[0] - side * 1.0, base[1] + 1.0),
            (midx - side * 2.2, midy + 3.0),
            (tipx - side * 3.6, tipy + 4.6),
            (hx + side * 18.5, hy - 41.5),
        ]
        c.polygon(inner, rgba(HAIR, 255), soft=0.4)
        # inner fur
        c.polygon([
            (base[0] - side * 1.5, base[1] - 1.5),
            (midx - side * 3.6, midy + 1.5),
            (tipx - side * 8.0, tipy + 10.5),
            (hx + side * 24.0, hy - 50.0),
        ], rgba(mix(SKIN_SHADE, BLUSH, 0.42), 230), soft=0.5)
        c.circle(base[0], base[1] + 2, 5.4, rgba(HAIR, 255), soft=1.2)

    # --- head silhouette (drawn after the hair so it wraps the strands)
    c.ellipse(hx, hy + 1, 42.0, 40.6, rgba(OUTLINE, 215), soft=0.7)
    c.ellipse(hx, hy + 1, 40.6, 39.2, rgba(SKIN, 255))
    # jaw taper: overlay to firm the chin
    c.ellipse(hx, hy + 15, 34.5, 30.0, rgba(SKIN, 255), soft=2.6)
    # soft shading under the bangs
    c.ellipse(hx, hy - 16, 39.0, 21.0, rgba(SKIN_SHADE, 85), soft=4.0)

    # --- bangs (front hair)
    c.ellipse(hx, hy - 22, 44.0, 30.0, rgba(OUTLINE, 200), soft=0.7)
    c.ellipse(hx, hy - 23.5, 42.6, 28.4, rgba(HAIR, 255))
    bang_pts = [
        (hx - 43, hy - 28), (hx - 44, hy - 16), (hx - 33, hy - 25),
        (hx - 24, hy - 14), (hx - 13, hy - 28), (hx - 2, hy - 17),
        (hx + 9, hy - 26), (hx + 20, hy - 14), (hx + 31, hy - 25),
        (hx + 43, hy - 16), (hx + 44, hy - 28), (hx + 30, hy - 42),
        (hx, hy - 47), (hx - 30, hy - 42),
    ]
    c.polygon(bang_pts, rgba(HAIR, 255), soft=0.45)
    # bang shading + strand highlights
    c.polygon([(hx - 30, hy - 22), (hx - 24, hy - 10), (hx - 20, hy - 24), (hx - 26, hy - 34)],
              rgba(HAIR_DEEP, 115), soft=1.2)
    c.polygon([(hx + 4, hy - 20), (hx + 9, hy - 20), (hx + 14, hy - 34), (hx + 9, hy - 38)],
              rgba(WHITE, 150), soft=1.2)
    for k, ox in ((-1, 16.0), (1, -12.0)):
        c.capsule((hx + ox, hy - 41), (hx + ox * 0.55, hy - 22), 2.0,
                  rgba(WHITE, 170), r1=0.8, soft=0.9)
    # side bangs framing the cheeks
    for side in (-1, 1):
        c.polygon([
            (hx + side * 40, hy - 16), (hx + side * 43, hy + 12),
            (hx + side * 33, hy + 24), (hx + side * 31, hy - 8),
        ], rgba(HAIR, 255), soft=0.5)
        c.polygon([
            (hx + side * 38, hy - 8), (hx + side * 41, hy + 8),
            (hx + side * 35, hy + 16), (hx + side * 34, hy - 4),
        ], rgba(HAIR_DEEP, 110), soft=1.0)

    # --- eyes
    ey = hy + 6.0
    _eye(c, hx - 17.5, ey, 10.8, 11.4, look=look, blink=blink_l, tilt=-0.10)
    _eye(c, hx + 17.5, ey, 10.8, 11.4, look=look, blink=blink_r, tilt=0.10)
    # brows (kept clear of the bang line so they read at pet size)
    c.capsule((hx - 26.0, ey - 21.0), (hx - 9.5, ey - 24.0), 1.6, rgba(HAIR_LINE, 225), r1=1.4, soft=0.5)
    c.capsule((hx + 26.0, ey - 21.0), (hx + 9.5, ey - 24.0), 1.6, rgba(HAIR_LINE, 225), r1=1.4, soft=0.5)
    # nose + mouth
    c.circle(hx, ey + 13.0, 0.9, rgba(SKIN_LINE, 170), soft=0.5)
    mw = 4.6 + 1.4 * smile
    c.capsule((hx - mw, ey + 16.6 + 0.9 * smile), (hx, ey + 19.8 + 1.2 * smile),
              0.95, rgba(SKIN_LINE, 230), r1=0.95, soft=0.4)
    c.capsule((hx, ey + 19.8 + 1.2 * smile), (hx + mw, ey + 16.6 + 0.9 * smile),
              0.95, rgba(SKIN_LINE, 230), r1=0.95, soft=0.4)
    # blush
    ba = 0.35 + 0.45 * blush
    for side in (-1, 1):
        c.ellipse(hx + side * 26.0, ey + 11.0, 6.6, 3.4, rgba(BLUSH, int(190 * ba)), soft=2.4)

    # --- crescent hair ornament (readable at pet size)
    px, py = hx + 24.0, hy - 36.0
    c.circle(px, py, 9.5, rgba(MOON, 80), soft=5.5)
    c.crescent(px, py, 7.4, rgba(GOLD, 255), bite=0.60, bite_dy=-0.26, bite_dx=0.46, soft=0.45)
    c.crescent(px, py, 6.2, rgba(GOLD_DEEP, 140), bite=0.60, bite_dy=-0.26, bite_dx=0.46, soft=0.9)
    c.star(px + 10.4, py - 8.0, 3.4, rgba(MOON_PALE, 240), inner=0.34, points=4, rot=0.4, soft=0.6)
    c.star(px - 8.8, py + 7.4, 2.4, rgba(WHITE, 220), inner=0.34, points=4, rot=0.9, soft=0.6)
    # small hair ribbon on the other side
    c.capsule((hx - 38, hy - 28), (hx - 45, hy - 22), 2.2, rgba(ROBE_LIGHT, 235), r1=1.4, soft=0.6)
    c.capsule((hx - 38, hy - 28), (hx - 42, hy - 36), 2.0, rgba(ROBE_LIGHT, 235), r1=1.2, soft=0.6)
    c.circle(hx - 38, hy - 28, 2.6, rgba(GOLD, 220), soft=0.7)


def draw_aura(c: Canvas, t=0.0):
    """Moonlit sparkles around the character.

    Deliberately no large soft ellipse: at low alpha it is invisible on a light
    desktop yet a colour-keyed (1-bit) window would still paint its dither.
    """
    for i, (sx, sy, sr, ph) in enumerate((
        (CX - 74, 76, 3.6, 0.0), (CX + 78, 96, 3.0, 1.1), (CX - 62, 172, 2.8, 2.0),
        (CX + 66, 180, 3.2, 0.6), (CX, 34, 2.6, 1.6),
    )):
        a = 150 + 100 * math.sin(t * math.tau + ph)
        c.star(sx, sy, sr, rgba(MOON_PALE, int(max(60, a))), inner=0.36, points=4,
               rot=ph, soft=0.8)
        c.circle(sx, sy, sr * 0.9, rgba(WHITE, 110), soft=2.2)


def compose(pose: dict, scale_ss: int = 4):
    """Render one sprite frame as a PIL RGBA image.

    pose keys: swing, bob, squash, tilt, look, blink_l, blink_r, smile, blush,
               ear_twitch, aura_t
    """
    from PIL import Image

    swing = pose.get("swing", 0.0)
    bob = pose.get("bob", 0.0)
    squash = pose.get("squash", 1.0)
    tilt = pose.get("tilt", 0.0)

    back = Canvas(W, H, ss=scale_ss)
    draw_aura(back, pose.get("aura_t", 0.0))
    draw_tails(back, swing=swing, glow=0.5)

    body = Canvas(W, H, ss=scale_ss)
    draw_body(body, squash=squash, arm_lift=pose.get("arm", 0.0))

    head = Canvas(W, H, ss=scale_ss)
    draw_head(
        head,
        tilt=tilt,
        look=pose.get("look", 0.0),
        blink_l=pose.get("blink_l", 0.0),
        blink_r=pose.get("blink_r", 0.0),
        smile=pose.get("smile", 0.0),
        blush=pose.get("blush", 0.0),
        ear_twitch=pose.get("ear_twitch", 0.0),
    )

    base = Image.alpha_composite(back.to_pil(), body.to_pil())
    head_img = head.to_pil()
    if abs(tilt) > 0.001:
        # rotate around the neck pivot (in PIL coords: x, H - y)
        pivot = (HEAD_C[0], H - (HEAD_C[1] + 30.0))
        head_img = head_img.rotate(-tilt, resample=Image.BICUBIC, center=pivot)
    base = Image.alpha_composite(base, head_img)

    if abs(bob) > 0.001:
        shifted = Image.new("RGBA", base.size, (0, 0, 0, 0))
        shifted.paste(base, (0, int(round(bob))), base)
        base = shifted
    return base
