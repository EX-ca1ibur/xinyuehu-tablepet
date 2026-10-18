"""Keep the 心月狐 pet alive exactly as long as DSH is running.

Started once at logon (see autostart/start-pet-at-logon.vbs, installed by
install-autostart.cmd). Every couple of seconds:

* DSH running, pet missing (never started or crashed) -> launch the pet, which
  respects its own PID lock, so a manually started instance is adopted rather
  than duplicated
* DSH gone -> stop the pet, then wait for DSH to come back

Process liveness uses :mod:`ctypes` and ``tasklist`` only — no PowerShell per
poll (too slow) and no decoding of localised process output.
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
DSH_HOME = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
LOCK_FILE = DSH_HOME / "xinyuehu-pet.lock"
WATCHDOG_LOCK = DSH_HOME / "xinyuehu-pet-watchdog.lock"
LOG_FILE = DSH_HOME / "xinyuehu-pet-watchdog.log"

PACKAGE_ROOT = HERE if (HERE / "src" / "run_pet.py").exists() else HERE.parent
PET_ENTRY = PACKAGE_ROOT / "src" / "run_pet.py"

DSH_EXE = "DeepSeek Harness.exe"
POLL_SECONDS = 2.0
RESTART_BACKOFF_SECONDS = 12.0
LOG_MAX_BYTES = 256 * 1024
KEEP_LOG_LINES = 400
ART_CHECK_SECONDS = 60.0

# Where the sprite atlas lives. If it disappears the pet still runs, but with
# the hand-drawn stand-in, which reads as "the wrong character" rather than an
# error - so the watchdog reports it instead of letting it pass unnoticed.
ATLAS_FILES = (
    Path.home() / ".codex" / "pets" / "hsin-moon-fox" / "spritesheet.webp",
    Path.home() / ".petdex" / "pets" / "hsin-moon-fox" / "spritesheet.webp",
)

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259


def log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_MAX_BYTES:
            kept = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            LOG_FILE.write_text("\n".join(kept[-KEEP_LOG_LINES:]) + "\n", encoding="utf-8")
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------- liveness
def pid_alive(pid: int) -> bool:
    """True only while the process is genuinely still running."""
    if pid <= 0:
        return False
    try:
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == STILL_ACTIVE
    except OSError:
        return False


def _tasklist_names() -> set[str]:
    """Image names of running processes (ASCII-safe decoding)."""
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                             capture_output=True, timeout=20,
                             creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return set()
    names: set[str] = set()
    for raw in (out.stdout or b"").splitlines():
        line = raw.decode("utf-8", errors="replace").strip()
        if not line.startswith('"'):
            continue
        name = line[1:].split('","', 1)[0]
        if name:
            names.add(name)
    return names


def dsh_running() -> bool:
    return DSH_EXE in _tasklist_names()


def pet_pid() -> int:
    try:
        return int(json.loads(LOCK_FILE.read_text(encoding="utf-8")).get("pid", 0))
    except (OSError, ValueError):
        return 0


def pet_running() -> bool:
    return pid_alive(pet_pid())


# ------------------------------------------------------------------------- pet
def start_pet() -> None:
    python_exe = resolve_python()
    try:
        subprocess.Popen([python_exe, str(PET_ENTRY)], cwd=str(PACKAGE_ROOT),
                         creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
        log(f"launched pet via {Path(python_exe).parent.name}/python.exe")
    except OSError as exc:
        log(f"failed to launch pet: {exc}")


def stop_pet() -> None:
    pid = pet_pid()
    if pid:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=15,
                           creationflags=CREATE_NO_WINDOW)
            log(f"stopped pet pid {pid} (DSH is gone)")
        except (OSError, subprocess.SubprocessError) as exc:
            log(f"failed to stop pet pid {pid}: {exc}")
    try:
        LOCK_FILE.unlink()
    except OSError:
        pass


def resolve_python() -> str:
    """Prefer the DSH bundled runtime (it is the one with Pillow/numpy)."""
    candidates = [
        DSH_HOME / "dsh-runtimes" / "dsh-primary-runtime" / "dependencies" / "python" / "python.exe",
        Path(sys.executable),
    ]
    for cand in candidates:
        if cand.exists():
            return str(cand)
    return sys.executable


def atlas_present() -> bool:
    return any(f.exists() for f in ATLAS_FILES)


# ------------------------------------------------------------------------ main
_SINGLETON_HANDLE = None


def _acquire_singleton() -> bool:
    """Claim the watchdog slot atomically.

    The previous check-then-write version raced: two watchdogs starting in the
    same instant both saw an empty lock and both kept running, which produced
    duplicate pets and a relaunch storm. An OS file lock is atomic, and the
    kernel releases it when the holder dies, so a stale lock cannot wedge us.
    """
    global _SINGLETON_HANDLE
    try:
        WATCHDOG_LOCK.parent.mkdir(parents=True, exist_ok=True)
        handle = open(WATCHDOG_LOCK, "a+b")
    except OSError:
        return True  # cannot lock: run rather than silently doing nothing
    try:
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except (ImportError, OSError):
        handle.close()
        return False
    handle.seek(0)
    handle.truncate()
    handle.write(json.dumps({"pid": os.getpid()}).encode("utf-8"))
    handle.flush()
    _SINGLETON_HANDLE = handle
    return True


def main(argv: list[str] | None = None) -> int:
    if not PET_ENTRY.exists():
        log(f"pet entry not found: {PET_ENTRY}")
        return 1
    if not _acquire_singleton():
        log("another watchdog is already running; exiting")
        return 0

    log(f"watchdog start (pid {os.getpid()})")
    backoff_until = 0.0
    was_dsh = None
    art_ok = True
    next_art_check = 0.0
    try:
        while True:
            now = time.time()
            up = dsh_running()
            if up != was_dsh:
                log("DSH is up" if up else "DSH is gone")
                was_dsh = up
            if now >= next_art_check:
                next_art_check = now + ART_CHECK_SECONDS
                present = atlas_present()
                if present != art_ok:
                    art_ok = present
                    if present:
                        log("sprite atlas is back; restarting the pet to use it")
                        stop_pet()
                    else:
                        log("WARNING: sprite atlas missing - the pet will draw the "
                            "hand-drawn stand-in. Restore it with "
                            "tools/restore_pet_art.py")
            if up:
                if not pet_running() and now >= backoff_until:
                    start_pet()
                    backoff_until = now + RESTART_BACKOFF_SECONDS
            elif pet_running():
                stop_pet()
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        log("watchdog interrupted")
    finally:
        # the OS lock is released on exit; leave the file so the next start can
        # lock it again (deleting it would race with a simultaneous starter)
        if _SINGLETON_HANDLE is not None:
            try:
                _SINGLETON_HANDLE.close()
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
