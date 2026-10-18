"""Sprite library: layered sheets -> ready-to-paste animation frames.

Baking keeps the character as a *base* sheet (aura + tails + body) plus a *head*
sheet (pose x blink). All compositing happens once here at startup; the finished
frames are also cached to ``assets/atlas_<size>.png`` so later launches are a
single file read.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[2] / "assets"

# pose -> milliseconds per animation phase
POSE_INTERVAL = {"idle": 260, "happy": 90}


class AssetsMissing(RuntimeError):
    """程序化回落立绘缺失（没有 ``assets/`` 目录时抛出）。

    调用方应当接住它并给出提示，而不是让 traceback 糊用户一脸。
    """

    ADVICE = (
        "缺少图片素材：assets/manifest.json 不存在。\n\n"
        "本程序需要角色图集才能显示桌宠，请任选其一：\n"
        "  1. npx petdex install hsin-moon-fox\n"
        "     （安装社区同人图集，推荐）\n"
        "  2. 把 assets/ 目录放回程序根目录\n"
        "     （自带立绘的烘焙产物）"
    )


class SpriteLibrary:
    def __init__(self, assets: Path = ASSETS, size: int | None = None,
                 use_cache: bool = True):
        self.assets = Path(assets)
        self.size = size
        try:
            self.manifest = json.loads(
                (self.assets / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AssetsMissing(AssetsMissing.ADVICE) from exc
        self.fw = int(self.manifest["frame_w"])
        self.fh = int(self.manifest["frame_h"])
        self._frames: dict[str, list[Image.Image]] = {}
        if size and use_cache and self._load_atlas():
            return
        try:
            self._build()
        except (OSError, KeyError) as exc:
            raise AssetsMissing(AssetsMissing.ADVICE) from exc
        if size and use_cache:
            self._save_atlas()

    # ------------------------------------------------------------------- cache
    def _atlas_path(self) -> Path:
        return self.assets / f"atlas_{self.size}.png"

    def _stamp(self) -> str:
        parts = []
        for meta in self.manifest["poses"].values():
            for key in ("base", "head"):
                f = self.assets / meta[key]
                parts.append(f"{f.name}:{int(f.stat().st_mtime)}:{f.stat().st_size}")
        return "|".join(parts)

    def _load_atlas(self) -> bool:
        path = self._atlas_path()
        side = path.with_suffix(".json")
        if not path.exists() or not side.exists():
            return False
        try:
            info = json.loads(side.read_text(encoding="utf-8"))
            if info.get("stamp") != self._stamp() or info.get("size") != self.size:
                return False
            sheet = Image.open(path).convert("RGBA")
        except (OSError, ValueError, KeyError):
            return False
        disp_h = self._disp_size()[1]
        row = 0
        for pose, meta in self.manifest["poses"].items():
            n = int(meta["phases"]) * int(meta["blink_levels"])
            frames = []
            for i in range(n):
                y = (row + i) * disp_h
                frames.append(sheet.crop((0, y, self.size, y + disp_h)).copy())
            self._frames[pose] = frames
            row += n
        sheet.close()
        return True

    def _save_atlas(self) -> None:
        disp_w, disp_h = self._disp_size()
        total = sum(int(m["phases"]) * int(m["blink_levels"])
                    for m in self.manifest["poses"].values())
        sheet = Image.new("RGBA", (disp_w, disp_h * total), (0, 0, 0, 0))
        y = 0
        for pose in self.manifest["poses"]:
            for frame in self._frames[pose]:
                sheet.alpha_composite(frame, (0, y))
                y += disp_h
        try:
            sheet.save(self._atlas_path())
            self._atlas_path().with_suffix(".json").write_text(
                json.dumps({"stamp": self._stamp(), "size": self.size}, ensure_ascii=False),
                encoding="utf-8")
        except OSError:
            pass
        sheet.close()

    # ------------------------------------------------------------------- build
    def _disp_size(self) -> tuple[int, int]:
        if not self.size:
            return self.fw, self.fh
        return self.size, int(round(self.size * self.fh / self.fw))

    def _build(self) -> None:
        w, h = self.fw, self.fh
        dw, dh = self._disp_size()
        for pose, meta in self.manifest["poses"].items():
            base = Image.open(self.assets / meta["base"]).convert("RGBA")
            head = Image.open(self.assets / meta["head"]).convert("RGBA")
            phases = int(meta["phases"])
            levels = int(meta["blink_levels"])
            cols = int(meta["cols"])

            def crop(sheet: Image.Image, i: int) -> Image.Image:
                cx0, cy0 = (i % cols) * w, (i // cols) * h
                return sheet.crop((cx0, cy0, cx0 + w, cy0 + h))

            base_frames = [crop(base, i) for i in range(phases)]

            def compose(args):
                level, p = args
                frame = Image.alpha_composite(base_frames[p], crop(head, level * phases + p))
                if self.size:
                    frame = frame.resize((dw, dh), Image.LANCZOS)
                return level * phases + p, frame

            jobs = [(lv, p) for lv in range(levels) for p in range(phases)]
            frames: list[Image.Image | None] = [None] * (phases * levels)
            with ThreadPoolExecutor(max_workers=4) as pool:
                for idx, frame in pool.map(compose, jobs):
                    frames[idx] = frame
            self._frames[pose] = [f for f in frames if f is not None]
            base.close()
            head.close()

    # ------------------------------------------------------------------ access
    @property
    def display_size(self) -> tuple[int, int]:
        return self._frames["idle"][0].size

    def phases(self, pose: str) -> int:
        return int(self.manifest["poses"].get(pose, self.manifest["poses"]["idle"])["phases"])

    def blink_levels(self, pose: str) -> int:
        return int(self.manifest["poses"].get(pose, self.manifest["poses"]["idle"])[
            "blink_levels"])

    def interval(self, pose: str) -> int:
        return POSE_INTERVAL.get(pose, 250)

    def frame(self, pose: str, phase: int, blink_level: int = 0) -> Image.Image:
        name = pose if pose in self.manifest["poses"] else "idle"
        frames = self._frames[name]
        n_phases = self.phases(name)
        n_levels = self.blink_levels(name)
        level = max(0, min(blink_level, n_levels - 1))
        return frames[level * n_phases + (phase % n_phases)]


def rebuild_atlas_cache(size: int) -> None:
    """Delete a cached atlas (used by the --rebuild flag)."""
    path = ASSETS / f"atlas_{size}.png"
    for p in (path, path.with_suffix(".json")):
        try:
            p.unlink()
        except OSError:
            pass
