"""HUD card: the "which model / what has it cost me" balloon.

Data comes from :mod:`pet.liveusage` — the session logs, which DSH appends to on
every step — rather than from ``usage-ledger.json``, which on this machine can
sit unchanged for a day and made the pet look frozen.

The pet window is colour-key transparent, which is binary: a pixel is either
opaque or fully see-through. There is therefore no real translucency, and the
card is drawn as a solid panel with a crisp border (a dithered glow read as dirt
at this size).
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import usage as usage_mod

# ------------------------------------------------------------------- geometry
# Vertical budget (k = 1, measured against a rendered ruler):
#   header 21 | model row 27 | underline 6 | context 17 | 4 spend rows x 19
#   | footer 16 | bottom padding 10  ->  183 + 12 = ~195
CARD_W = 236
CARD_H = 196
TAIL_H = 11
PAD = 15
RADIUS = 17

# ---------------------------------------------------------------------- style
BG_DARK = (22, 24, 38)
BG_TINT = (44, 48, 78)
BORDER = (150, 178, 255)
ACCENT = (168, 216, 255)
TEXT_MAIN = (245, 247, 255)
TEXT_DIM = (168, 176, 208)
GOLD = (247, 205, 106)
TEAL = (124, 236, 226)
GREEN = (126, 226, 158)
AMBER = (255, 196, 110)
RED = (255, 130, 140)

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

FONT_CANDIDATES = (
    "msyhbd.ttc", "msyh.ttc", "Microsoft YaHei Bold", "Microsoft YaHei",
    "simhei.ttf", "Deng.ttf", "NotoSansCJK-Bold.ttc", "arialbd.ttf", "arial.ttf",
)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = ("b" if bold else "r", size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    search = Path("C:/Windows/Fonts")
    names = FONT_CANDIDATES if bold else FONT_CANDIDATES[1:] + FONT_CANDIDATES[:1]
    font: ImageFont.FreeTypeFont | None = None
    for name in names:
        candidate = search / name
        if candidate.exists():
            try:
                font = ImageFont.truetype(str(candidate), size)
                break
            except OSError:
                continue
    if font is None:
        font = ImageFont.load_default(size)
    _FONT_CACHE[key] = font
    return font


def _rounded_mask(w: int, h: int, radius: int) -> Image.Image:
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    return mask


def _fit(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> str:
    if font.getlength(text) <= max_w:
        return text
    ell = "…"
    out = text
    while out and font.getlength(out + ell) > max_w:
        out = out[:-1]
    return out + ell


def status_color(live) -> tuple[int, int, int]:
    """Dot colour: is the reading live, stale, or unreadable?"""
    if not getattr(live, "ok", True):
        return RED
    age = time.time() - (getattr(live, "last_ms", 0.0) or 0.0) / 1000.0
    if not getattr(live, "last_ms", 0.0):
        return AMBER
    if age < 120:
        return GREEN
    return AMBER if age < 3600 else RED


def _money(value: float) -> str:
    return usage_mod.format_money(value, "CNY")


def render(live, balance: float | None = None, balance_currency: str = "CNY",
           width: int = CARD_W, scale: float = 1.0,
           art_warning: str = "") -> Image.Image:
    """Render the balloon as an RGBA image (card + pointer tail).

    Body, border, text and pointer are opaque, so the balloon composites cleanly
    onto a colour-keyed window. ``art_warning`` prepends a loud strip when the
    real sprite atlas is missing and a stand-in character is being drawn.
    """
    w = int(round(width))
    k = w / CARD_W
    warn_h = int(round(26 * k)) if art_warning else 0
    h = int(round(CARD_H * k)) + warn_h
    tail_h = int(round(TAIL_H * k))
    pad = max(8, int(round(PAD * k)))
    radius = max(6, int(round(RADIUS * k)))
    cx = w // 2

    s = max(0.62, scale * k)
    f_name = _font(int(round(13.0 * s)), bold=True)
    f_model = _font(int(round(19.5 * s)), bold=True)
    f_lbl = _font(int(round(11.5 * s)))
    f_val = _font(int(round(14.0 * s)), bold=True)
    f_small = _font(int(round(10.0 * s)))

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    # ---- solid body with a subtle top-lit gradient
    body = Image.new("RGBA", (w, h), (*BG_DARK, 255))
    grad = Image.new("L", (1, h), 0)
    gp = grad.load()
    for y in range(h):
        gp[0, y] = int(118 * (1.0 - y / max(1, h)) ** 1.4)
    body = Image.composite(Image.new("RGBA", (w, h), (*BG_TINT, 255)), body,
                           grad.resize((w, h)))
    img.paste(body, (0, 0), _rounded_mask(w, h, radius))

    # ---- pointer tail
    d = ImageDraw.Draw(img)
    d.polygon([(cx - 13, h - 2), (cx + 13, h - 2), (cx, h + tail_h)],
              fill=(*BG_DARK, 255))

    # ---- warning strip: the stand-in character is being drawn
    top = 0
    if art_warning:
        strip = Image.new("RGBA", (w, warn_h), (0, 0, 0, 0))
        ImageDraw.Draw(strip).rounded_rectangle(
            (0, 0, w - 1, warn_h * 2), radius=radius, fill=(122, 34, 44, 255))
        img.alpha_composite(strip, (0, 0))
        tw = f_small.getlength(art_warning)
        d.text(((w - tw) / 2, int(round(warn_h / 2 - 6 * k))), art_warning,
               font=f_small, fill=(255, 226, 226, 255))
        d.line([(pad, warn_h), (w - pad, warn_h)], fill=(255, 140, 140, 150), width=1)
        top = warn_h

    # ---- crisp border (no glow: a colour-keyed window can only dither one)
    bw = max(1, int(round(1.35 * k)))
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius,
                        outline=(*ACCENT, 230), width=bw)
    d.line([(cx - 13, h - 1), (cx, h + tail_h - 1)], fill=(*ACCENT, 230), width=bw)
    d.line([(cx + 13, h - 1), (cx, h + tail_h - 1)], fill=(*ACCENT, 230), width=bw)
    d.rounded_rectangle((bw + 2, bw + 2, w - bw - 3, h - bw - 3),
                        radius=max(3, radius - bw - 1),
                        outline=(255, 255, 255, 30), width=1)

    # ---- header: name + live status dot + effort tag
    y = top + pad + int(1 * k)
    dot_r = max(3, int(round(4.2 * k)))
    dot_c = status_color(live)
    dcx, dcy = pad + dot_r, y + int(round(8 * k))
    d.ellipse((dcx - dot_r, dcy - dot_r, dcx + dot_r, dcy + dot_r), fill=(*dot_c, 255))
    d.ellipse((dcx - dot_r // 2 - 1, dcy - dot_r // 2 - 1,
               dcx + dot_r // 2 - 1, dcy + dot_r // 2 - 1), fill=(255, 255, 255, 215))

    label = "心月狐"
    d.text((dcx + dot_r + int(7 * k), y), label, font=f_name, fill=TEXT_MAIN)
    lw = f_name.getlength(label)
    effort = getattr(live, "effort", "") or ""
    if effort:
        etag = f"推理 {effort}"
        ex = dcx + dot_r + int(7 * k) + lw + int(8 * k)
        ew = f_small.getlength(etag) + int(11 * k)
        eh = int(round(15 * k))
        d.rounded_rectangle((ex, y + int(1 * k), ex + ew, y + int(1 * k) + eh),
                            radius=eh // 2, fill=(*ACCENT, 52), outline=(*ACCENT, 150))
        d.text((ex + int(5.5 * k), y + int(2.5 * k)), etag, font=f_small, fill=ACCENT)
    # right side: today's spend, the number that matters most
    today = _money(getattr(live, "today_spend", 0.0))
    d.text((w - pad - f_val.getlength(today), y + int(1 * k)), today,
           font=f_val, fill=GOLD)

    # ---- model row
    my = y + int(round(21 * k))
    d.text((pad, my), _fit(getattr(live, "model", "") or "(未知模型)", f_model,
                           w - 2 * pad), font=f_model, fill=TEXT_MAIN)
    d.line([(pad, my + int(round(27 * k))), (w - pad, my + int(round(27 * k)))],
           fill=(*ACCENT, 70), width=1)

    # ---- context pressure (the live "how full is the window" signal)
    cy = my + int(round(34 * k))
    pct = float(getattr(live, "context_pct", 0.0))
    ctxt = f"{getattr(live, 'context_tokens', 0) / 1000:.0f}K / " \
           f"{getattr(live, 'context_window', 0) / 1_000_000:.0f}M"
    d.text((pad, cy + int(2 * k)), "上下文", font=f_lbl, fill=TEXT_DIM)
    pw = w - 2 * pad - int(round(64 * k))
    px0 = pad + int(round(64 * k))
    ph = max(4, int(round(7 * k)))
    bar_col = GREEN if pct < 60 else (AMBER if pct < 85 else RED)
    d.rounded_rectangle((px0, cy + int(4 * k), px0 + pw, cy + int(4 * k) + ph),
                        radius=ph // 2, fill=(255, 255, 255, 34))
    fill_w = int(pw * min(1.0, pct / 100.0))
    if fill_w > 0:
        d.rounded_rectangle((px0, cy + int(4 * k), px0 + fill_w, cy + int(4 * k) + ph),
                            radius=ph // 2, fill=(*bar_col, 255))
    d.text((w - pad - f_small.getlength(f"{pct:.0f}%"), cy + int(1 * k)),
           f"{pct:.0f}%", font=f_small, fill=bar_col)

    # ---- spend rows
    rows = [
        ("今日", _money(getattr(live, "today_spend", 0.0)), GOLD),
        ("累计", _money(getattr(live, "total_spend", 0.0)), TEXT_MAIN),
        ("本会话", _money(getattr(live, "session_spend", 0.0)), ACCENT),
        ("余额", usage_mod.format_money(balance, balance_currency), TEAL),
    ]
    ry = cy + int(round(17 * k))
    step = int(round(19 * k))
    for i, (lbl, val, col) in enumerate(rows):
        yy = ry + i * step
        d.text((pad, yy + int(3 * k)), lbl, font=f_lbl, fill=TEXT_DIM)
        d.text((w - pad - f_val.getlength(val), yy), val, font=f_val, fill=col)

    # ---- footer: its own band below the last spend row
    foot = f"实时 · {getattr(live, 'sessions_seen', 0)} 个会话日志"
    if not getattr(live, "ok", True) and getattr(live, "error", ""):
        foot = getattr(live, "error", "")[:34]
    d.line([(pad, h - int(round(17 * k))), (w - pad, h - int(round(17 * k)))],
           fill=(*ACCENT, 46), width=1)
    d.text((pad, h - int(round(14 * k))), foot, font=f_small,
           fill=GREEN if getattr(live, "ok", True) else RED)
    return img
