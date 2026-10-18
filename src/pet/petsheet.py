"""Real 心月狐 sprite atlas installed by petdex (Codex/DSH pet contract).

Atlas = 8 columns x 9 rows, cell 192x208, rows in fixed order:
  0 idle, 1 running-right, 2 running-left, 3 waving, 4 jumping,
  5 failed, 6 waiting, 7 running, 8 review
Rows may use fewer than 8 columns; the per-row frame counts resolve from the
manifest when present, otherwise the hatch-pet contract table.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ROW_ORDER = ("idle", "running-right", "running-left", "waving", "jumping",
             "failed", "waiting", "running", "review")
DEFAULT_FRAME_COUNTS = (6, 8, 8, 4, 5, 8, 6, 6, 6)

# pose -> ms per frame (gentle rhythms; the pet is decorative, not a metronome)
TRACK_INTERVAL = {
    "idle": 520,
    "waiting": 520,
    "running": 300,
    "running-right": 260,
    "running-left": 260,
    "waving": 300,
    "jumping": 200,
    "failed": 480,
    "review": 420,
}

CANDIDATE_DIRS = (
    Path.home() / ".codex" / "pets" / "hsin-moon-fox",
    Path.home() / ".petdex" / "pets" / "hsin-moon-fox",
)


def find_pet_dir(extra: Path | None = None) -> Path | None:
    """The installed pet directory, if its manifest is there.

    Deliberately does not require the spritesheet: a manifest without the sheet
    is a *broken install* that the caller should report loudly, not silently
    treat as "no pet installed".
    """
    for candidate in ((extra,) if extra else ()) + CANDIDATE_DIRS:
        if candidate and (candidate / "pet.json").exists():
            return candidate
    return None


def atlas_missing_reason(pet_dir: Path | None = None) -> str:
    """Why the real atlas cannot be used, or '' when it is fine."""
    d = pet_dir if pet_dir is not None else find_pet_dir()
    if d is None:
        return "未安装心月狐素材"
    for name in ("spritesheet.webp", "spritesheet.png"):
        if (d / name).exists():
            return ""
    return "素材文件丢失"


class PetSheet:
    """All 9 tracks of the installed 心月狐 atlas, ready to paste."""

    def __init__(self, pet_dir: Path, size: int = 224):
        self.dir = Path(pet_dir)
        sheet_path = self._resolve_sheet()
        img = Image.open(sheet_path).convert("RGBA")
        cols, rows = 8, 9
        self.cell_w = img.width // cols
        self.cell_h = img.height // rows
        self.size = int(size)
        self.disp_w = self.size
        self.disp_h = int(round(self.size * self.cell_h / self.cell_w))

        counts = self._resolve_counts()
        self.tracks: dict[str, list[Image.Image]] = {}
        for row, name in enumerate(ROW_ORDER):
            n = max(1, min(cols, counts[row] if row < len(counts) else cols))
            frames = []
            for col in range(n):
                cell = img.crop((col * self.cell_w, row * self.cell_h,
                                 (col + 1) * self.cell_w, (row + 1) * self.cell_h))
                frames.append(cell.resize((self.disp_w, self.disp_h), Image.LANCZOS))
            self.tracks[name] = frames
        img.close()

    # ------------------------------------------------------------------ helpers
    def _resolve_sheet(self) -> Path:
        import json

        manifest = json.loads((self.dir / "pet.json").read_text(encoding="utf-8"))
        block = manifest.get("sprite2d") or manifest
        rel = block.get("spritesheetPath") or "spritesheet.webp"
        path = self.dir / rel
        if not path.exists():
            for alt in ("spritesheet.webp", "spritesheet.png"):
                if (self.dir / alt).exists():
                    return self.dir / alt
            raise FileNotFoundError(f"spritesheet not found in {self.dir}")
        return path

    def _resolve_counts(self) -> tuple[int, ...]:
        import json

        try:
            manifest = json.loads((self.dir / "pet.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return DEFAULT_FRAME_COUNTS
        block = manifest.get("sprite2d") or {}
        frames = block.get("frames") or manifest.get("frames")
        if isinstance(frames, list) and len(frames) == 9 and all(
                isinstance(v, int) and v > 0 for v in frames):
            return tuple(frames)
        return DEFAULT_FRAME_COUNTS

    # ------------------------------------------------------------------- access
    def phases(self, track: str) -> int:
        return len(self.tracks.get(track) or self.tracks["idle"])

    def interval(self, track: str) -> int:
        return TRACK_INTERVAL.get(track, 400)

    def frame(self, track: str, phase: int, blink_level: int = 0) -> Image.Image:
        frames = self.tracks.get(track) or self.tracks["idle"]
        return frames[phase % len(frames)]

    def tracks_available(self) -> list[str]:
        return list(self.tracks)


class ProceduralSheet:
    """Fallback: the hand-drawn procedural character in the same 9-track shape.

    Only four tracks exist in the baked sheets, so the rest alias onto them and
    the pet degrades gracefully when the real atlas is not installed.
    """

    ALIAS = {
        "idle": "idle", "waiting": "idle", "review": "idle", "failed": "idle",
        "running": "idle", "running-right": "happy", "running-left": "happy",
        "waving": "happy", "jumping": "happy",
    }

    def __init__(self, size: int = 224):
        from .sprites import SpriteLibrary

        self._lib = SpriteLibrary(size=size)
        self.disp_w, self.disp_h = self._lib.display_size

    def phases(self, track: str) -> int:
        return self._lib.phases(self.ALIAS.get(track, "idle"))

    def interval(self, track: str) -> int:
        base = self._lib.interval(self.ALIAS.get(track, "idle"))
        return {"running": 200, "running-right": 160, "running-left": 160,
                "jumping": 160, "waving": 220}.get(track, base)

    def frame(self, track: str, phase: int, blink_level: int = 0) -> Image.Image:
        alias = self.ALIAS.get(track, "idle")
        return self._lib.frame(alias, phase, blink_level)

    def tracks_available(self) -> list[str]:
        return list(ROW_ORDER)


def make_sheet(size: int = 224, pet_dir: Path | None = None):
    """Real atlas when installed, otherwise the procedural fallback."""
    found = find_pet_dir(pet_dir)
    if found is not None:
        try:
            return PetSheet(found, size=size), found
        except (OSError, ValueError, KeyError):
            pass
    return ProceduralSheet(size=size), None
