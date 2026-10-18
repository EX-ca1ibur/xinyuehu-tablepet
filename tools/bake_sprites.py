"""Bake the character into layered sprite sheets.

Split so animation stays cheap at runtime:

* ``tails_<pose>.png``  — aura + tails + body, one column per animation phase
* ``head.png``          — head/face swatches (pose x blink level)

The runtime composites base[phase] + head[pose][blink], which means a blink only
costs one small paste instead of a full character re-render.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402

from pet import character  # noqa: E402
from pet.character import Canvas  # noqa: E402

ASSETS = ROOT / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

W, H = int(character.W), int(character.H)

# Windows compositing key the runtime uses. A partial pixel is kept only when
# its *effective* visibility (alpha x composited contrast vs. the key) clears
# this bar; anything fainter would only ever show as a dirty speck.
KEY_RGB = (13, 14, 18)
MIN_VISIBLE = 46.0

# ---- tuned tail style (see tools/sweep_tails*.py for how this was chosen)
character.set_tail_style(count=5, base_dy=36, spread=118, length=120, extra=44,
                         curl=14, width=17.0)

IDLE_PHASES = 16
HAPPY_PHASES = 10
BLINK_LEVELS = (0.0, 0.55, 1.0)


def _render_base(pose: dict) -> Image.Image:
    back = Canvas(W, H)
    character.draw_aura(back, pose.get("aura_t", 0.0))
    character.draw_tails(back, swing=pose.get("swing", 0.0))

    body = Canvas(W, H)
    character.draw_body(body, squash=pose.get("squash", 1.0), arm_lift=pose.get("arm", 0.0))
    return Image.alpha_composite(back.to_pil(), body.to_pil())


def _render_head(pose: dict) -> Image.Image:
    head = Canvas(W, H)
    character.draw_head(
        head,
        look=pose.get("look", 0.0),
        blink_l=pose.get("blink_l", 0.0),
        blink_r=pose.get("blink_r", 0.0),
        smile=pose.get("smile", 0.0),
        blush=pose.get("blush", 0.0),
        ear_twitch=pose.get("ear_twitch", 0.0),
    )
    return head.to_pil()


def _render_layers(pose: dict):
    """Return (base_rgba, head_rgba) for one pose."""
    return _render_base(pose), _render_head(pose)


def _idle_pose(i: int, n: int = IDLE_PHASES) -> dict:
    u = i / n
    tau = math.tau
    return dict(
        swing=4.2 * math.sin(tau * u),
        squash=1.0 + 0.016 * math.sin(tau * u),
        aura_t=u,
        look=0.10 * math.sin(tau * u + 0.9),
        ear_twitch=0.5 * max(0.0, math.sin(tau * u * 2.0 - 1.1)) ** 3,
        smile=0.18,
    )


def _happy_pose(i: int, n: int = HAPPY_PHASES) -> dict:
    u = i / n
    tau = math.tau
    bounce = abs(math.sin(math.pi * u))  # one bounce per cycle
    return dict(
        swing=9.0 * math.sin(tau * u),
        squash=1.0 + 0.05 * bounce,
        aura_t=u,
        look=0.0,
        ear_twitch=1.0 * bounce,
        smile=1.0,
        blush=1.0,
        arm=0.7 * bounce,
    )


def _grid(images: list[Image.Image], cols: int | None = None) -> tuple[Image.Image, int, int]:
    n = len(images)
    cols = cols or n
    rows = (n + cols - 1) // cols
    sheet = Image.new("RGBA", (W * cols, H * rows), (0, 0, 0, 0))
    for idx, im in enumerate(images):
        r, c = divmod(idx, cols)
        sheet.alpha_composite(im, (c * W, r * H))
    return sheet, cols, rows


def clean_alpha(img: Image.Image) -> Image.Image:
    """Resolve partial alpha the way a colour-keyed window has to.

    A colour-key window is 1-bit transparent: a pixel either paints or it does
    not. Dithering half-invisible pixels reads as dirty specks on a real desktop,
    so each partial pixel is resolved by its *effective* visibility — how far the
    composited colour actually lands from the key, scaled by how often it would
    be painted:

        visible  -> forced fully opaque
        invisible -> dropped entirely
    """
    import numpy as np

    arr = np.asarray(img.convert("RGBA")).astype(np.float32)
    a = arr[..., 3:4] / 255.0
    key = np.array(KEY_RGB, dtype=np.float32).reshape(1, 1, 3)
    composed = arr[..., :3] * a + key * (1.0 - a)
    contrast = np.abs(composed - key).max(axis=2)
    effective = a[..., 0] * contrast

    keep = (a[..., 0] >= 0.72) | (effective >= MIN_VISIBLE)
    arr[..., 3] = np.where(keep, 255.0, 0.0)
    return Image.fromarray(arr.astype("uint8"), mode="RGBA")


def main() -> int:
    t0 = time.time()
    manifest = {"frame_w": W, "frame_h": H, "poses": {}}

    for pose_name, maker, phases in (
        ("idle", _idle_pose, IDLE_PHASES),
        ("happy", _happy_pose, HAPPY_PHASES),
    ):
        bases: list[Image.Image] = []
        heads: list[Image.Image] = []
        for p in range(phases):
            pose = maker(p, phases)
            bases.append(_render_base(pose))
            print(f"  {pose_name} base {p + 1}/{phases}", flush=True)
        for blink in BLINK_LEVELS:
            for p in range(phases):
                pose = maker(p, phases)
                heads.append(_render_head({**pose, "blink_l": blink, "blink_r": blink}))
            print(f"  {pose_name} heads blink={blink} done", flush=True)

        cols = phases
        base_sheet, bc, br = _grid(bases, cols=cols)
        head_sheet, hc, hr = _grid(heads, cols=cols)
        base_sheet = clean_alpha(base_sheet)
        head_sheet = clean_alpha(head_sheet)
        base_sheet.save(ASSETS / f"base_{pose_name}.png")
        head_sheet.save(ASSETS / f"head_{pose_name}.png")
        manifest["poses"][pose_name] = {
            "phases": phases,
            "blink_levels": len(BLINK_LEVELS),
            "cols": cols,
            "rows": br,
            "base": f"base_{pose_name}.png",
            "head": f"head_{pose_name}.png",
        }
        print(f"{pose_name}: base {base_sheet.size}, head {head_sheet.size}", flush=True)

    manifest["tail_style"] = {
        "count": character.TAIL_COUNT, "base_dy": character.TAIL_BASE_DY,
        "spread": character.TAIL_SPREAD, "length": character.TAIL_LEN,
        "extra": character.TAIL_EXTRA, "curl": character.TAIL_CURL,
        "width": character.TAIL_W,
    }
    (ASSETS / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"baked in {time.time() - t0:.1f}s -> {ASSETS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
