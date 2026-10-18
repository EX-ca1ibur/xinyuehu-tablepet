"""Exercise the watchdog lifecycle without touching the real DSH app.

Phase 1  DSH up            -> watchdog starts the pet
Phase 2  DSH "closed" (stub) -> watchdog stops the pet
Phase 3  DSH up again      -> watchdog relaunches the pet
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
DSH_HOME = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
LOCK = DSH_HOME / "xinyuehu-pet.lock"
LOG = DSH_HOME / "xinyuehu-pet-watchdog.log"
NO_WINDOW = 0x08000000

sys.path.insert(0, str(PKG))
import run_pet_watchdog as w  # noqa: E402


def pet_pid() -> int:
    try:
        return int(json.loads(LOCK.read_text(encoding="utf-8")).get("pid", 0))
    except (OSError, ValueError):
        return 0


def wait_for(predicate, seconds: float, label: str):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if predicate():
            return True, time.time() - t0
        time.sleep(0.5)
    return False, time.time() - t0


print("DSH detected:", w.dsh_running())
if not w.dsh_running():
    print("DSH is not running; phase 1 cannot be tested")
    raise SystemExit(2)

# clean slate: no pet, no stale locks
old = pet_pid()
if w.pid_alive(old):
    subprocess.run(["taskkill", "/PID", str(old), "/T", "/F"], capture_output=True)
    print(f"killed pre-existing pet pid {old}")
for f in (LOCK, DSH_HOME / "xinyuehu-pet-watchdog.lock"):
    try:
        f.unlink()
    except OSError:
        pass

watchdog = subprocess.Popen([sys.executable, str(PKG / "run_pet_watchdog.py")],
                            creationflags=NO_WINDOW)
print("watchdog pid", watchdog.pid)

# ---- phase 1
ok, dt = wait_for(lambda: w.pet_running(), 25, "pet start")
pid1 = pet_pid()
print(f"PHASE1 watchdog started the pet: pid={pid1} alive={w.pid_alive(pid1)} "
      f"({dt:.1f}s) -> {'PASS' if ok and w.pid_alive(pid1) else 'FAIL'}")

# also confirm the pet window really exists
out = subprocess.run(["tasklist", "/FI", f"PID eq {pid1}", "/FO", "CSV", "/NH"],
                     capture_output=True, creationflags=NO_WINDOW)
print("  tasklist says:", out.stdout.decode("utf-8", "replace").strip()[:90])

# ---- phase 2: stub "DSH closed" in a separate process and stop the pet once
stopper = subprocess.run(
    [sys.executable, "-c",
     f"import sys;sys.path.insert(0,r'{PKG}');import run_pet_watchdog as w;w.stop_pet()"],
    creationflags=NO_WINDOW, capture_output=True, timeout=60)
time.sleep(1.0)
print(f"PHASE2 pet stopped when DSH is gone: alive={w.pid_alive(pid1)} "
      f"-> {'PASS' if not w.pid_alive(pid1) else 'FAIL'}")

# ---- phase 3: the running watchdog must notice and relaunch
ok3, dt3 = wait_for(lambda: w.pet_running() and pet_pid() != pid1, 30, "pet restart")
pid3 = pet_pid()
print(f"PHASE3 watchdog relaunched the pet: pid={pid3} alive={w.pid_alive(pid3)} "
      f"({dt3:.1f}s) -> {'PASS' if ok3 and w.pid_alive(pid3) else 'FAIL'}")

watchdog.terminate()
time.sleep(0.5)
print("--- watchdog log ---")
try:
    print("\n".join(LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-10:]))
except OSError:
    print("(no log)")
