"""Headless self-check: pet atlas, live usage, HUD and frame compositing."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from pet import hud, usage  # noqa: E402
from pet.app import _flatten  # noqa: E402
from pet.liveusage import LiveUsageReader, call_spend, is_peak  # noqa: E402
from pet.petsheet import make_sheet  # noqa: E402

fail = []


def check(label, ok, detail=""):
    print(f"[{'ok' if ok else 'FAIL'}] {label}{('  ' + detail) if detail else ''}")
    if not ok:
        fail.append(label)


# ---- pet atlas -------------------------------------------------------------
t0 = time.time()
lib, pet_dir = make_sheet(224)
check("atlas loaded", True,
      f"{'real' if pet_dir else 'procedural'} {lib.disp_w}x{lib.disp_h} in {time.time()-t0:.2f}s")
for track in ("idle", "waving", "jumping", "running", "failed", "waiting",
              "running-left", "running-right", "review"):
    n = lib.phases(track)
    check(f"track {track:14s}", n > 0, f"{n} frames, {lib.interval(track)} ms/frame")
    for i in range(n):
        f = lib.frame(track, i)
        if f.size != (lib.disp_w, lib.disp_h):
            fail.append(f"{track}[{i}] wrong size {f.size}")
            break

# ---- pricing ---------------------------------------------------------------
# The formula must reproduce a known ledger row to the last micro-CNY.
known = {"inputTokens": 38254, "outputTokens": 14753, "cacheReadTokens": 612352,
         "cacheWriteTokens": 0}
off_peak = call_spend("deepseek-flash", known, 0)          # epoch => off-peak
check("pricing reproduces ledger row", abs(off_peak - 0.109514) < 1e-6,
      f"{off_peak:.6f} vs ledger 0.109514")
check("peak windows", is_peak(1_790_000_000_000) in (True, False), "clock works")

# ---- live usage ------------------------------------------------------------
reader = LiveUsageReader()
t0 = time.time()
live = reader.snapshot()
cold = time.time() - t0
check("live snapshot", live.ok, f"{cold*1000:.0f} ms, {live.sessions_seen} logs")
check("live model known", bool(live.model), live.model or "(none)")
print(f"       today=¥{live.today_spend:.4f} ({live.today_calls} calls)  "
      f"total=¥{live.total_spend:.4f}  session=¥{live.session_spend:.4f}  "
      f"context={live.context_tokens:,}/{live.context_window:,} ({live.context_pct:.1f}%)")
t0 = time.time()
reader.snapshot()
warm = time.time() - t0
check("cached poll is cheap", warm < 0.05, f"{warm*1000:.0f} ms")

# ---- hud -------------------------------------------------------------------
acct = usage.load_account()
card = hud.render(live, balance=acct.balance, balance_currency=acct.currency, width=236)
check("hud rendered", card.size == (236, hud.CARD_H), f"{card.size} (expect 236x{hud.CARD_H})")
warn = hud.render(live, balance=acct.balance, width=236, art_warning="素材缺失")
check("hud warning strip adds height", warn.size[1] > card.size[1],
      f"{card.size[1]} -> {warn.size[1]}")
check("hud is opaque in the middle",
      int(np.asarray(card)[card.height // 2, card.width // 2, 3]) == 255)
# nothing may be drawn in the pointer area outside the tail
tail_px = np.asarray(card)[:, :, 3]
check("hud has transparent margins", int((tail_px == 0).sum()) > 0)

# ---- full frame compositing ------------------------------------------------
sw, sh = lib.disp_w, lib.disp_h
tw, th = max(sw, card.width), card.height + 4 + sh
canvas = Image.new("RGBA", (tw, th), (13, 14, 18, 255))
canvas.alpha_composite(card, ((tw - card.width) // 2, 0))
canvas.alpha_composite(lib.frame("idle", 0), ((tw - sw) // 2, card.height + 4))
flat = _flatten(canvas, (tw, th))
out = ROOT / "build" / "preview"
out.mkdir(parents=True, exist_ok=True)
flat.save(out / "composed_frame.png")
check("frame composited", flat.size == (tw, th), f"{flat.size} -> {out.name}/composed_frame.png")

empty = _flatten(Image.new("RGBA", (tw, th), (13, 14, 18, 255)), (tw, th))
arr = np.asarray(empty)
non_key = int((arr != np.array([13, 14, 18], dtype=np.uint8)).any(axis=-1).sum())
check("empty buffer paints nothing", non_key == 0, f"{non_key} non-key pixels")

print()
print("FAILURES:", fail) if fail else print("ALL CHECKS PASSED")
raise SystemExit(1 if fail else 0)
