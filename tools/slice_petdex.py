"""Slice the installed petdex 心月狐 atlas into per-track frames for the HUD pet."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
SHEET = HOME / ".codex" / "pets" / "hsin-moon-fox" / "spritesheet.webp"
OUT = ROOT / "build" / "petdex-preview"

ROW_ORDER = ("idle", "running-right", "running-left", "waving", "jumping",
             "failed", "waiting", "running", "review")


def main() -> int:
    if not SHEET.exists():
        print("missing:", SHEET)
        return 1
    img = Image.open(SHEET).convert("RGBA")
    print("sheet", img.size)
    cols = 8
    rows = 9
    cw, ch = img.width // cols, img.height // rows
    print("cell", cw, "x", ch)

    OUT.mkdir(parents=True, exist_ok=True)
    # contact sheet: one row per track, every column, on a light/dark split
    sheet = Image.new("RGBA", (cw * cols, ch * rows), (246, 247, 251, 255))
    for r, name in enumerate(ROW_ORDER):
        for c in range(cols):
            cell = img.crop((c * cw, r * ch, (c + 1) * cw, (r + 1) * ch))
            sheet.alpha_composite(cell, (c * cw, r * ch))
    sheet.convert("RGB").resize((sheet.width // 2, sheet.height // 2),
                                Image.LANCZOS).save(OUT / "atlas_contact.png")

    # per-track alpha coverage tells us which cells actually have art
    for r, name in enumerate(ROW_ORDER):
        used = []
        for c in range(cols):
            a = img.crop((c * cw, r * ch, (c + 1) * cw, (r + 1) * ch)).getchannel("A")
            used.append(round(a.getextrema()[1] / 255, 2))
        print(f"  row {r} {name:14s} max-alpha per column: {used}")
    print("saved", OUT / "atlas_contact.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
