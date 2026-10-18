"""Restore the 心月狐 sprite atlas by re-downloading it via the petdex CLI.

The atlas lives in the petdex/Codex pet directories and those files can go
missing (antivirus quarantine, a manual clean, a cloud-sync eviction). When that
happens the pet silently falls back to the hand-drawn stand-in, which looks like
"the wrong character" rather than an error - so give the user one obvious repair
path.

Downloads the CLI into a temp directory, so the project stays dependency-free.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SLUG = "hsin-moon-fox"
PET_DIRS = (Path.home() / ".codex" / "pets", Path.home() / ".petdex" / "pets")
DSH_HOME = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
PYTHON = DSH_HOME / "dsh-runtimes" / "dsh-primary-runtime" / "dependencies" / "python" / "python.exe"
NODE = DSH_HOME / "dsh-runtimes" / "dsh-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe"
PNPM = DSH_HOME / "dsh-runtimes" / "dsh-primary-runtime" / "dependencies" / "pnpm" / "bin" / "pnpm.mjs"

CREATE_NO_WINDOW = 0x08000000


def atlas_present() -> bool:
    for base in PET_DIRS:
        d = base / SLUG
        if (d / "pet.json").exists():
            for name in ("spritesheet.webp", "spritesheet.png"):
                if (d / name).exists():
                    return True
    return False


def _run(args: list[str], cwd: Path | None = None) -> int:
    try:
        proc = subprocess.run(args, cwd=str(cwd) if cwd else None,
                              capture_output=True, text=True, timeout=600,
                              creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[!] 命令无法执行: {exc}")
        return 1
    tail = (proc.stdout or "").strip().splitlines()[-6:]
    for line in tail:
        print("   ", line)
    err = (proc.stderr or "").strip().splitlines()[-4:]
    for line in err:
        print("   ", line)
    return proc.returncode


def main() -> int:
    if atlas_present():
        print("[i] 素材已存在，无需修复。")
        return 0
    if not NODE.exists() or not PNPM.exists():
        print(f"[!] 找不到 DSH 自带的 node/pnpm:\n    {NODE}\n    {PNPM}")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="petdex-restore-"))
    try:
        (tmp / "package.json").write_text('{"name":"restore","private":true}',
                                          encoding="ascii")
        print("[1/2] 下载 petdex CLI ...")
        if _run([str(NODE), str(PNPM), "--dir", str(tmp), "add", "petdex"]) != 0:
            print("[!] petdex CLI 安装失败")
            return 1
        cli = tmp / "node_modules" / "petdex" / "dist" / "petdex.js"
        if not cli.exists():
            print(f"[!] 找不到 CLI 入口: {cli}")
            return 1
        print(f"[2/2] 重新下载 {SLUG} ...")
        if _run([str(NODE), str(cli), "install", SLUG]) != 0:
            print("[!] 素材下载失败")
            return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if atlas_present():
        print("[ok] 素材已恢复。重启桌宠即可（退出后看门狗会自动拉起）。")
        return 0
    print("[!] 下载完成但仍找不到素材文件，请检查:", ", ".join(str(p) for p in PET_DIRS))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
