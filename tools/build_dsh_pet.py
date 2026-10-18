"""Render the procedural 心月狐 character into the DSH pet atlas contract.

NOTE — reference / spare path only, not part of the live install. The pet that
is actually installed is the petdex community atlas (loaded by
``src/pet/petsheet.py``), which uses this same contract with real artwork. This
script is kept because it documents the contract and can produce a self-made
atlas if the downloaded one ever goes away.

Contract (see @linxin666/dsh-pet README):
  8 columns x 9 rows, cell 192x208, rows in fixed order
  0 idle, 1 running-right, 2 running-left, 3 waving, 4 jumping,
  5 failed, 6 waiting, 7 running, 8 review
Unused cells stay fully transparent.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402

from pet import character  # noqa: E402
from pet.character import Canvas  # noqa: E402

# ---- contract constants
CELL_W, CELL_H = 192, 208
COLUMNS = 8
ROWS = 9
ROW_ORDER = ("idle", "running-right", "running-left", "waving", "jumping",
             "failed", "waiting", "running", "review")

# ---- how much of the 232x248 design canvas to use, and where to sit
SCALE = 0.78
FEET_Y = 199          # design-space y that lands on the cell floor
CENTER_X = character.CX

_pose_cache: dict[tuple, Image.Image] = {}


def _render(pose: dict) -> Image.Image:
    """One character frame in design space."""
    back = Canvas(int(character.W), int(character.H))
    character.draw_aura(back, pose.get("aura_t", 0.0))
    character.draw_tails(back, swing=pose.get("swing", 0.0))

    body = Canvas(int(character.W), int(character.H))
    character.draw_body(body, squash=pose.get("squash", 1.0),
                        arm_lift=pose.get("arm", 0.0))

    head = Canvas(int(character.W), int(character.H))
    character.draw_head(
        head,
        look=pose.get("look", 0.0),
        blink_l=pose.get("blink_l", 0.0),
        blink_r=pose.get("blink_r", 0.0),
        smile=pose.get("smile", 0.0),
        blush=pose.get("blush", 0.0),
        ear_twitch=pose.get("ear_twitch", 0.0),
    )
    out = Image.alpha_composite(back.to_pil(), body.to_pil())
    return Image.alpha_composite(out, head.to_pil())


def frame(pose: dict) -> Image.Image:
    key = tuple(sorted((k, round(v, 4) if isinstance(v, float) else v)
                       for k, v in pose.items()))
    hit = _pose_cache.get(key)
    if hit is None:
        hit = _render(pose)
        _pose_cache[key] = hit

    lean = float(pose.get("_lean", 0.0))
    if abs(lean) > 0.01:
        # tilt about the feet so the body swings like a pendulum
        hit = hit.rotate(lean, resample=Image.BICUBIC, center=(CENTER_X, character.GROUND_Y))

    cell = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    src = hit.resize((int(round(hit.width * SCALE)), int(round(hit.height * SCALE))),
                     Image.LANCZOS)
    dx = int(round(CELL_W / 2 - CENTER_X * SCALE))
    dy = int(round(FEET_Y - character.GROUND_Y * SCALE - float(pose.get("_lift", 0.0))))
    cell.alpha_composite(src, (dx, dy))
    return cell


# ------------------------------------------------------------------ the tracks
def _blink(i: int, every: int, width: int = 2) -> float:
    """Blink level for frame i of a loop: 1.0 shut, 0.55 half, else open."""
    p = i % every
    if p == 0:
        return 1.0
    if p == width:
        return 0.55
    return 0.0


def track_idle(n: int = 8) -> list[Image.Image]:
    out = []
    for i in range(n):
        u = i / n
        out.append(frame(dict(
            swing=4.0 * math.sin(math.tau * u),
            squash=1.0 + 0.016 * math.sin(math.tau * u),
            aura_t=u,
            look=0.10 * math.sin(math.tau * u + 0.9),
            blink_l=_blink(i, 5), blink_r=_blink(i, 5),
            smile=0.2, ear_twitch=0.4 * max(0.0, math.sin(math.tau * u * 2 - 1.1)) ** 3,
        )))
    return out


def _run(n: int = 8, direction: int = 1) -> list[Image.Image]:
    """Leaning bob used for both run tracks; the right one is mirrored later."""
    out = []
    for i in range(n):
        u = i / n
        lean = 7.0
        out.append(frame(dict(
            swing=3.5 * direction - 6.0 * math.sin(math.tau * u),
            squash=1.0 - 0.030 * math.cos(math.tau * u),
            aura_t=u,
            look=0.45,
            smile=0.6,
            ear_twitch=0.5 + 0.5 * math.sin(math.tau * u),
            _lean=lean,
        )))
    return out


def track_waving(n: int = 8) -> list[Image.Image]:
    out = []
    for i in range(n):
        u = i / n
        wave = math.sin(math.tau * u)
        out.append(frame(dict(
            swing=5.0 * wave,
            squash=1.0 + 0.02 * abs(wave),
            aura_t=u,
            arm=0.55 + 0.45 * abs(wave),
            look=-0.35,
            smile=0.75,
            blush=0.35,
            ear_twitch=0.5 + 0.5 * wave,
            blink_l=_blink(i, 6), blink_r=_blink(i, 6),
        )))
    return out


def track_jumping(n: int = 8) -> list[Image.Image]:
    """One arc: crouch, launch, apex, land."""
    heights = (0.0, 0.0, 6.0, 15.0, 21.0, 15.0, 6.0, 0.0)
    squashes = (0.94, 1.05, 1.06, 1.0, 0.97, 1.0, 1.04, 0.95)
    out = []
    for i in range(n):
        out.append(frame(dict(
            swing=3.0 * math.sin(math.pi * i / n),
            squash=squashes[i],
            aura_t=i / n,
            arm=0.85,
            smile=0.9,
            blush=0.55,
            ear_twitch=1.0,
            look=0.0,
            _lift=heights[i],
        )))
    return out


def track_failed(n: int = 8) -> list[Image.Image]:
    out = []
    for i in range(n):
        u = i / n
        droop = 0.5 + 0.5 * math.cos(math.tau * u)
        out.append(frame(dict(
            swing=1.5 * math.sin(math.tau * u),
            squash=0.965 - 0.015 * droop,
            aura_t=u,
            look=-0.5,
            smile=0.0,
            ear_twitch=-0.9 * droop,      # ears fold back
            blink_l=0.35, blink_r=0.35,   # heavy-lidded
            _lean=-4.0 * droop,
        )))
    return out


def track_waiting(n: int = 8) -> list[Image.Image]:
    out = []
    for i in range(n):
        u = i / n
        out.append(frame(dict(
            swing=2.5 * math.sin(math.tau * u + 0.5),
            squash=1.0 + 0.010 * math.sin(math.tau * u),
            aura_t=u,
            look=-0.15,
            smile=0.3,
            ear_twitch=0.3 * max(0.0, math.sin(math.tau * u)),
            blink_l=_blink(i, 7), blink_r=_blink(i, 7),
        )))
    return out


def track_running(n: int = 8) -> list[Image.Image]:
    """The 'working' loop: busier tails, focused forward look."""
    out = []
    for i in range(n):
        u = i / n
        out.append(frame(dict(
            swing=7.0 * math.sin(math.tau * u),
            squash=1.0 + 0.020 * math.sin(math.tau * u * 2),
            aura_t=u,
            look=0.3,
            smile=0.5,
            ear_twitch=0.4,
            blink_l=_blink(i, 8), blink_r=_blink(i, 8),
        )))
    return out


def track_review(n: int = 8) -> list[Image.Image]:
    """Review state: leaning in to look closely."""
    out = []
    for i in range(n):
        u = i / n
        out.append(frame(dict(
            swing=2.0 * math.sin(math.tau * u),
            squash=1.01 + 0.012 * math.sin(math.tau * u),
            aura_t=u,
            look=0.55,
            smile=0.35,
            ear_twitch=0.7,
            arm=0.25,
            _lean=5.0,
        )))
    return out


def build_atlas() -> Image.Image:
    tracks = {
        "idle": track_idle(),
        "running-left": _run(direction=-1),
        "waving": track_waving(),
        "jumping": track_jumping(),
        "failed": track_failed(),
        "waiting": track_waiting(),
        "running": track_running(),
        "review": track_review(),
    }
    tracks["running-right"] = [im.transpose(Image.FLIP_LEFT_RIGHT)
                               for im in tracks["running-left"]]

    atlas = Image.new("RGBA", (CELL_W * COLUMNS, CELL_H * ROWS), (0, 0, 0, 0))
    for row, name in enumerate(ROW_ORDER):
        frames = tracks[name]
        for col, im in enumerate(frames[:COLUMNS]):
            atlas.alpha_composite(im, (col * CELL_W, row * CELL_H))
        print(f"  row {row} {name}: {len(frames[:COLUMNS])} frames", flush=True)
    return atlas


if __name__ == "__main__":
    out = ROOT / "build" / "dsh-pet"
    out.mkdir(parents=True, exist_ok=True)
    sheet = build_atlas()
    sheet.save(out / "spritesheet.png")
    print("atlas", sheet.size, "->", out / "spritesheet.png")
