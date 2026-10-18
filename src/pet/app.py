"""心月狐 desktop pet — shows the current DSH model and what it has cost you.

A frameless, always-on-top, colour-keyed transparent window holding two stacked
panels that behave as one draggable unit::

    +---------------------------+
    | * 心月狐  推理 max   ¥0.00 |   <- HUD balloon
    | deepseek-flash            |
    | 今日 / 累计 / 余额         |
    +-------------v-------------+
              ( sprite )
"""
from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import os
import time
from pathlib import Path


def _enable_dpi_awareness() -> str:
    """Make Tk report real pixels.

    Without this the process is DPI-virtualised: Tk would report 3200x2000 on a
    200%-scaled display while coordinates are interpreted in 1600x1000 logical
    space, which parks the pet off-screen.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor v2
        return "per-monitor"
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return "system"
    except (AttributeError, OSError):
        return "none"


DPI_MODE = _enable_dpi_awareness()

import tkinter as tk  # noqa: E402  (after DPI setup, deliberately)

import numpy as np  # noqa: E402
from PIL import Image, ImageTk  # noqa: E402

from . import hud  # noqa: E402
from . import usage as usage_mod  # noqa: E402
from .liveusage import LiveUsageReader  # noqa: E402
from .petsheet import atlas_missing_reason, make_sheet  # noqa: E402
from .sprites import AssetsMissing, rebuild_atlas_cache  # noqa: E402

KEY = "#0d0e12"
KEY_RGB = (13, 14, 18)
SPRITE_SIZE = 224
HUD_WIDTH = 236
HUD_GAP = 4
DRAG_SLOP = 4
ANIM_MS = 80
DATA_MS = 1500
TICK_MS = 40
SNAP_MARGIN = 18

# animation sequences: list of (track, loops) played in order
SEQ_PET = (("waving", 2),)
SEQ_HAPPY = (("jumping", 1), ("running", 3))
SEQ_WORK = (("running", 4),)

DSH_HOME = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
STATE_FILE = DSH_HOME / "xinyuehu-pet.json"
LOCK_FILE = DSH_HOME / "xinyuehu-pet.lock"

_NOISE = None

# ---- Win32 geometry check -------------------------------------------------
# Tk and Windows can disagree about the pixel mapping of an override-redirect
# window on a scaled display (Windows places it at half size/offset while Tk
# reports the requested numbers). The check below runs *after* the window is
# mapped, measures the real rectangle, and re-places the window with the
# discrepancy folded in.
_user32 = getattr(ctypes, "windll", None) and ctypes.windll.user32


def _top_hwnd(root) -> int:
    if not _user32:
        return 0
    try:
        hwnd = root.winfo_id()
    except tk.TclError:
        return 0
    for _ in range(8):
        parent = _user32.GetParent(hwnd)
        if not parent:
            break
        hwnd = parent
    return hwnd


def _real_rect(hwnd: int):
    if not _user32 or not hwnd:
        return None

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    rect = RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def _noise(shape: tuple[int, int]) -> np.ndarray:
    """Stable per-pixel noise so the dither never flickers between frames."""
    global _NOISE
    if _NOISE is None or _NOISE.shape != shape:
        _NOISE = np.random.default_rng(20261012).random(shape).astype(np.float32)
    return _NOISE


def _flatten(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Composite RGBA onto the colour key, dithering partial alpha to 1-bit."""
    arr = np.asarray(img.convert("RGBA"))
    if arr.shape[0] != size[1] or arr.shape[1] != size[0]:
        padded = np.zeros((size[1], size[0], 4), dtype=np.uint8)
        padded[..., :3] = KEY_RGB
        padded[..., 3] = 255
        h = min(size[1], arr.shape[0])
        w = min(size[0], arr.shape[1])
        padded[:h, :w] = arr[:h, :w]
        arr = padded
    a = arr[..., 3].astype(np.float32) / 255.0
    rgb = arr[..., :3].astype(np.float32)
    key = np.array(KEY_RGB, dtype=np.float32)
    out = rgb * a[..., None] + key * (1.0 - a[..., None])
    hard = (a >= 0.999) | (_noise(a.shape) < a)
    out[~hard] = key
    return Image.fromarray(out.astype(np.uint8), mode="RGB")


class PetState:
    DEFAULTS = {
        "x": None,
        "y": None,
        "size": SPRITE_SIZE,
        "show_hud": True,
        "snap_bottom": True,
        "topmost": True,
    }

    def __init__(self, path: Path = STATE_FILE):
        self.path = path
        self.data = dict(self.DEFAULTS)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            pass



def _fatal_missing_assets(detail: str) -> None:
    """缺素材时弹个框说清楚，而不是丢 traceback。"""
    try:
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("心月狐桌宠 · 缺少素材", detail)
        root.destroy()
    except Exception:  # noqa: BLE001 - 无 GUI 环境（CI/headless）时退化为打印
        print(detail)
    raise SystemExit(1)


class XinyuehuPet:
    def __init__(self, *, sprite_size: int = SPRITE_SIZE, show_hud: bool = True,
                 demo: bool = False, rebuild: bool = False):
        self.state = PetState()
        self.demo = demo
        self.sprite_size = int(self.state.data.get("size") or sprite_size)
        if rebuild:
            rebuild_atlas_cache(self.sprite_size)

        try:
            self.lib, self.pet_dir = make_sheet(self.sprite_size)
        except AssetsMissing as exc:
            _fatal_missing_assets(str(exc))
        self.using_real_art = self.pet_dir is not None
        # A missing atlas must be loud: silently drawing the stand-in is exactly
        # how the user ends up seeing "the wrong character" with no error at all.
        self.art_warning = "" if self.using_real_art else atlas_missing_reason()
        self.sprite_w, self.sprite_h = self.lib.disp_w, self.lib.disp_h
        self.show_hud = bool(self.state.data.get("show_hud", True)) and show_hud

        # data: live from the session logs (the ledger goes stale for a day)
        self.reader: LiveUsageReader | None = None if demo else LiveUsageReader()
        self.live = usage_mod.demo_live() if demo else self.reader.snapshot()
        self.account = usage_mod.load_account()
        self.hud_img: Image.Image | None = None
        self.hud_photo: ImageTk.PhotoImage | None = None
        self._hud_key = None
        self.photo: ImageTk.PhotoImage | None = None

        # animation
        self.track = "idle"
        self.phase = 0
        self.queue: list[list] = []          # [[track, loops_left], ...]
        self.last_anim = 0.0
        self.last_data = 0.0
        self._today_seen = round(self.live.today_spend, 4)

        # drag bookkeeping
        self._drag_origin = (0, 0, 0, 0)
        self._dragged = False
        self._click_hit = False

        # last geometry request, and whether the pixel mapping has been settled
        self._want = (0, 0, 0, 0)
        self._geom_fixed = False

        self._build_window()
        self._build_menu()
        self._place_initial()

        atexit.register(self._cleanup)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

    # ------------------------------------------------------------------ window
    def _build_window(self) -> None:
        self.root = tk.Tk()
        self.root.title("心月狐 · DSH")
        self.root.overrideredirect(True)
        self.root.configure(bg=KEY)
        self.root.attributes("-topmost", bool(self.state.data.get("topmost", True)))
        try:
            self.root.attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass
        try:
            self.root.wm_attributes("-toolwindow", True)
        except tk.TclError:
            pass
        # real screen size (DPI aware) — deliberately distinct from the sprite size
        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()
        self.label = tk.Label(self.root, bd=0, highlightthickness=0, bg=KEY)
        self.label.pack()
        self.label.bind("<Button-1>", self._on_press)
        self.label.bind("<B1-Motion>", self._on_drag)
        self.label.bind("<ButtonRelease-1>", self._on_release)
        self.label.bind("<Button-3>", self._on_right)
        self.label.bind("<Double-Button-1>", lambda _e: self.pet_it())
        self.root.bind("<Escape>", lambda _e: self.quit())

    # ---------------------------------------------------------------- geometry
    def _layout(self) -> tuple[int, int, int, int]:
        """(total_w, hud_x, sprite_x, sprite_y) for the current HUD state."""
        hw, hh = self.hud_img.size if (self.show_hud and self.hud_img) else (0, 0)
        total_w = max(self.sprite_w, hw)
        hud_x = (total_w - hw) // 2 if hw else 0
        sprite_x = (total_w - self.sprite_w) // 2
        sprite_y = (hh + HUD_GAP) if hw else 0
        return total_w, hud_x, sprite_x, sprite_y

    def _total_size(self) -> tuple[int, int]:
        total_w, _hx, _sx, sprite_y = self._layout()
        return total_w, sprite_y + self.sprite_h

    def _place_initial(self) -> None:
        self._ensure_hud(force=True)
        tw, th = self._total_size()
        x, y = self.state.data.get("x"), self.state.data.get("y")
        if not self._usable_position(x, y, tw, th):
            # first run, or the saved spot is off-screen (monitor/DPI change)
            x, y = self.screen_w - tw - 40, self.screen_h - th - 70
        x = max(0, min(int(x), max(0, self.screen_w - tw)))
        y = max(0, min(int(y), max(0, self.screen_h - th)))
        self._set_geometry(tw, th, x, y)
        self.state.data.update({"x": self.root.winfo_x(), "y": self.root.winfo_y()})

    def _usable_position(self, x, y, tw: int, th: int) -> bool:
        """Reuse a saved position only when the pet would be really visible."""
        if x is None or y is None:
            return False
        try:
            x, y = int(x), int(y)
        except (TypeError, ValueError):
            return False
        if x <= 0 and y <= 0:
            return False  # never a deliberate spot, and the old default
        visible_w = min(x + tw, self.screen_w) - max(x, 0)
        visible_h = min(y + th, self.screen_h) - max(y, 0)
        return visible_w >= tw * 0.6 and visible_h >= th * 0.4

    def _apply_geometry(self, x: int | None = None, y: int | None = None) -> None:
        tw, th = self._total_size()
        if x is None:
            x = self.root.winfo_x()
        if y is None:
            y = self.root.winfo_y()
        x = max(-self.sprite_w // 3, min(int(x), self.screen_w - tw + self.sprite_w // 3))
        y = max(0, min(int(y), self.screen_h - 20))
        self._set_geometry(tw, th, x, y)

    def _set_geometry(self, tw: int, th: int, x: int, y: int) -> None:
        """Request a geometry, in Tk's pixel space, and make Tk apply it."""
        self._want = (tw, th, x, y)
        self.root.geometry(f"{tw}x{th}+{x}+{y}")
        self.root.update_idletasks()

    def _verify_geometry(self, attempts: int = 3) -> None:
        """Fold in any Tk<->Windows pixel-mapping discrepancy, once, after mapping."""
        if not _user32 or self._geom_fixed:
            return
        rect = _real_rect(_top_hwnd(self.root))
        if rect is None:
            return
        _rx, _ry, rw, rh = rect
        tw, th, x, y = self._want
        if rw <= 0 or rh <= 0:
            return
        sx, sy = tw / rw, th / rh
        if abs(sx - 1.0) < 0.02 and abs(sy - 1.0) < 0.02:
            self._geom_fixed = True          # mapping is 1:1, nothing to do
            return
        self._geom_fixed = True
        if attempts <= 0:
            return
        nx = x if abs(sx - 1.0) < 0.02 else rect[0] * sx
        ny = y if abs(sy - 1.0) < 0.02 else rect[1] * sy
        self.root.geometry(f"{int(tw * sx)}x{int(th * sy)}+{int(nx)}+{int(ny)}")
        self.root.update_idletasks()
        # one re-check: if the mapping is uniform, this now lands exactly
        rect2 = _real_rect(_top_hwnd(self.root))
        if rect2 and abs(rect2[2] - tw) <= 2 and abs(rect2[3] - th) <= 2:
            return
        self._geom_fixed = False
        self.root.after(220, lambda: self._verify_geometry(attempts - 1))

    # ------------------------------------------------------------------ events
    def _sprite_hit(self, x: int, y: int) -> bool:
        _tw, _hx, sx, sy = self._layout()
        return sx <= x < sx + self.sprite_w and sy <= y < sy + self.sprite_h

    def _on_press(self, event) -> None:
        self._drag_origin = (event.x_root, event.y_root,
                             self.root.winfo_x(), self.root.winfo_y())
        self._dragged = False
        self._click_hit = self._sprite_hit(event.x, event.y)

    def _on_drag(self, event) -> None:
        ox, oy, wx, wy = self._drag_origin
        dx, dy = event.x_root - ox, event.y_root - oy
        if not self._dragged and abs(dx) + abs(dy) < DRAG_SLOP:
            return
        self._dragged = True
        self._apply_geometry(wx + dx, wy + dy)

    def _real_pos(self) -> tuple[int, int]:
        return self.root.winfo_x(), self.root.winfo_y()

    def _on_release(self, _event) -> None:
        if self._dragged:
            tw, th = self._total_size()
            x, y = self._real_pos()
            if self.state.data.get("snap_bottom", True) and y > self.screen_h - th - 190:
                y = self.screen_h - th - SNAP_MARGIN
            x = max(0, min(x, self.screen_w - tw))
            y = max(0, min(y, self.screen_h - th))
            self._set_geometry(tw, th, x, y)
            x, y = self._real_pos()
            self.state.data.update({"x": x, "y": y})
            self.state.save()
        elif self._click_hit:
            self.pet_it()

    def _on_right(self, event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    # -------------------------------------------------------------------- menu
    def _build_menu(self) -> None:
        self.var_hud = tk.BooleanVar(value=self.show_hud)
        self.var_top = tk.BooleanVar(value=bool(self.state.data.get("topmost", True)))
        self.var_snap = tk.BooleanVar(value=bool(self.state.data.get("snap_bottom", True)))
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="摸摸头", command=self.pet_it)
        m.add_command(label="跳一个", command=self.cheer)
        m.add_separator()
        m.add_checkbutton(label="显示用量浮窗", variable=self.var_hud,
                          command=self._toggle_hud)
        m.add_checkbutton(label="总在最前", variable=self.var_top, command=self._toggle_top)
        m.add_checkbutton(label="贴底吸附", variable=self.var_snap,
                          command=self._toggle_snap)
        size = tk.Menu(m, tearoff=0)
        for label, px in (("小 160", 160), ("中 200", 200), ("大 224", 224),
                          ("特大 288", 288)):
            size.add_command(label=label, command=lambda p=px: self.set_size(p))
        m.add_cascade(label="大小", menu=size)
        m.add_separator()
        m.add_command(label="立即刷新数据", command=self.refresh_data_now)
        m.add_command(label="打开发用量账本", command=self._open_ledger)
        m.add_separator()
        m.add_command(label="退出", command=self.quit)
        self.menu = m

    def _toggle_hud(self) -> None:
        self.show_hud = bool(self.var_hud.get())
        self.state.data["show_hud"] = self.show_hud
        self.state.save()
        self._resize_window()

    def _toggle_top(self) -> None:
        value = bool(self.var_top.get())
        self.root.attributes("-topmost", value)
        self.state.data["topmost"] = value
        self.state.save()

    def _toggle_snap(self) -> None:
        self.state.data["snap_bottom"] = bool(self.var_snap.get())
        self.state.save()

    # ---------------------------------------------------------------- commands
    def set_size(self, px: int) -> None:
        self.sprite_size = int(px)
        try:
            self.lib, self.pet_dir = make_sheet(self.sprite_size)
        except AssetsMissing as exc:
            _fatal_missing_assets(str(exc))
        self.using_real_art = self.pet_dir is not None
        self.sprite_w, self.sprite_h = self.lib.disp_w, self.lib.disp_h
        self.phase = 0
        self.state.data["size"] = self.sprite_size
        self.state.save()
        self._resize_window()

    def _resize_window(self) -> None:
        x, y = self._real_pos()
        tw, th = self._total_size()
        x = max(0, min(x, max(0, self.screen_w - tw)))
        y = max(0, min(y, max(0, self.screen_h - th)))
        self._set_geometry(tw, th, x, y)
        x, y = self._real_pos()
        self.state.data.update({"x": x, "y": y})
        self.state.save()
        self._draw()

    def refresh_data_now(self) -> None:
        self.last_data = 0.0
        self._pull_data()
        self._draw()

    def _open_ledger(self) -> None:
        try:
            os.startfile(usage_mod.LEDGER)  # noqa: S606  (Windows shell open)
        except OSError:
            pass

    def pet_it(self) -> None:
        self.play(SEQ_PET)

    def cheer(self) -> None:
        self.play(SEQ_HAPPY)

    # ------------------------------------------------------------------- frame
    def _pull_data(self) -> None:
        new = usage_mod.demo_live() if self.demo else self.reader.snapshot()
        spent_delta = round(new.today_spend, 4) - self._today_seen
        self.live = new
        if spent_delta > 0.0004:
            # new spend landed: the model just did some work
            self._today_seen = round(new.today_spend, 4)
            self.play(SEQ_WORK)
        if not self.demo:
            self.account = usage_mod.load_account()
        self._ensure_hud()

    def _ensure_hud(self, force: bool = False) -> None:
        if not self.show_hud:
            return
        key = (self.live.model, self.live.effort, round(self.live.today_spend, 4),
               round(self.live.total_spend, 4), round(self.live.session_spend, 4),
               round(self.live.context_pct, 1), self.live.balance_key(),
               self.live.ok)
        if not force and self._hud_key == key and self.hud_img is not None:
            return
        img = hud.render(self.live, balance=self.account.balance,
                         balance_currency=self.account.currency, width=HUD_WIDTH,
                         art_warning=self.art_warning)
        resized = self.hud_img is None or img.size != self.hud_img.size
        self.hud_img = img
        self.hud_photo = ImageTk.PhotoImage(_flatten(img, img.size))
        self._hud_key = key
        if resized and hasattr(self, "root"):
            self._resize_window()

    def _advance(self) -> None:
        """Step one animation frame; sequences play out then fall back to idle."""
        interval_frames = max(1, int(round(self.lib.interval(self.track) / ANIM_MS)))
        self._frame_in_phase = getattr(self, "_frame_in_phase", 0) + 1
        if self._frame_in_phase < interval_frames:
            return
        self._frame_in_phase = 0
        self.phase += 1
        if self.phase < self.lib.phases(self.track):
            return
        # this track finished: take the next queued item, else return to idle
        self.phase = 0
        while self.queue:
            track, loops = self.queue[0]
            if loops > 1:
                self.queue[0][1] = loops - 1
                self.track = track
                return
            self.queue.pop(0)
            remaining = self.queue[0][0] if self.queue else "idle"
            self.track = remaining
            return
        self.track = "idle"

    def play(self, sequence) -> None:
        self.queue = [[track, loops] for track, loops in sequence]
        if self.queue:
            self.track, self.phase = self.queue[0][0], 0
            self._frame_in_phase = 0

    @property
    def blink_level(self) -> int:
        return 0

    def _draw(self) -> None:
        if self.hud_img is None and self.show_hud:
            self._ensure_hud(force=True)
        tw, th = self._total_size()
        canvas = Image.new("RGBA", (tw, th), (*KEY_RGB, 255))
        _tw, hud_x, sprite_x, sprite_y = self._layout()
        if self.show_hud and self.hud_img is not None:
            canvas.alpha_composite(self.hud_img, (hud_x, 0))
        canvas.alpha_composite(self.lib.frame(self.track, self.phase), (sprite_x, sprite_y))
        self.photo = ImageTk.PhotoImage(_flatten(canvas, (tw, th)))
        self.label.configure(image=self.photo)

    # -------------------------------------------------------------------- loop
    def _tick(self) -> None:
        now = time.time()
        if now - self.last_data >= DATA_MS / 1000.0:
            self.last_data = now
            self._pull_data()
        if now - self.last_anim >= ANIM_MS / 1000.0:
            self.last_anim = now
            self._advance()
            self._draw()
        self.root.after(TICK_MS, self._tick)

    def run(self) -> None:
        self._resize_window()
        # the window must be mapped before the real rectangle can be measured
        self.root.after(260, self._verify_geometry)
        self.root.after(TICK_MS, self._tick)
        self.root.mainloop()

    def _cleanup(self) -> None:
        try:
            self.state.data.update({"x": self.root.winfo_x(), "y": self.root.winfo_y()})
        except tk.TclError:
            pass
        self.state.save()
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass

    def quit(self) -> None:
        self._cleanup()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


# --------------------------------------------------------------------- process
def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == STILL_ACTIVE
    except OSError:
        return False


def _acquire_lock() -> bool:
    if LOCK_FILE.exists():
        try:
            pid = int(json.loads(LOCK_FILE.read_text(encoding="utf-8")).get("pid", 0))
        except (OSError, ValueError):
            pid = 0
        if _pid_alive(pid):
            return False
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCK_FILE.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    except OSError:
        pass
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="心月狐 desktop pet for DSH")
    parser.add_argument("--size", type=int, default=SPRITE_SIZE, help="sprite pixel size")
    parser.add_argument("--no-hud", action="store_true", help="start with the HUD hidden")
    parser.add_argument("--rebuild", action="store_true", help="rebuild the sprite atlas")
    parser.add_argument("--demo", action="store_true", help="use demo values (screenshots)")
    parser.add_argument("--force", action="store_true", help="allow a second instance")
    args = parser.parse_args(argv)

    if not args.force and not _acquire_lock():
        print("心月狐已经在运行了（右击桌宠 → 退出 可关闭）")
        return 0

    pet = XinyuehuPet(sprite_size=args.size, show_hud=not args.no_hud,
                      demo=args.demo, rebuild=args.rebuild)
    pet.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
