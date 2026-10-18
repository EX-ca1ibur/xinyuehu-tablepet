"""Better model discovery: line-oriented parse of the cordis YAML layers."""
from __future__ import annotations

import os
import re
from pathlib import Path


def find_model_config(path: Path, target_id: str = "agent-default-model"):
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    idx = None
    for i, line in enumerate(lines):
        if re.match(rf"\s*-?\s*id:\s*{re.escape(target_id)}\s*$", line):
            idx = i
            break
    if idx is None:
        return None

    # walk forward to this entry's `config:` block, then collect key/values
    cfg_idx = None
    base_indent = len(lines[idx]) - len(lines[idx].lstrip())
    for j in range(idx + 1, min(idx + 40, len(lines))):
        line = lines[j]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent and re.match(r"\s*-?\s*id:", line):
            break
        if re.match(r"\s*config:\s*$", line):
            cfg_idx = j
            break
    if cfg_idx is None:
        return None

    cfg_indent = len(lines[cfg_idx]) - len(lines[cfg_idx].lstrip())
    out: dict[str, str] = {}
    for j in range(cfg_idx + 1, len(lines)):
        line = lines[j]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= cfg_indent:
            break
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*):\s*(.+?)\s*$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip("'\"")
    return out or None


if __name__ == "__main__":
    home = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
    prof = Path(os.environ.get("DSH_PROFILE_DIR", home / "profiles" / "desktop"))
    for p in (prof / "cordis.patch.yml", prof / "cordis.yml"):
        print(p.name, "->", find_model_config(p))
