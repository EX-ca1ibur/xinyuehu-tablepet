"""Inspect the live DSH session log for usage / cost fields.

The session log is the only store DSH writes mid-conversation, so it is the
candidate source for a真·real-time usage display.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import zstandard as zstd

SESSION = Path.home() / ".dsh" / "sessions" / "--D-OneDrive-Desktop-deepseek~0020project--" / \
    "session-2c7997f2-39a2-4be1-8723-a910f6798c0a" / "session.v4.jsonl.zstd"

if len(sys.argv) > 1:
    SESSION = Path(sys.argv[1])

print("log:", SESSION.name, f"{SESSION.stat().st_size/1024:.0f} KB")

with SESSION.open("rb") as fh:
    reader = zstd.ZstdDecompressor().stream_reader(fh)
    raw = reader.read()

lines = raw.decode("utf-8", errors="replace").splitlines()
print(f"decompressed: {len(raw)/1024:.0f} KB, {len(lines)} lines")

kinds = Counter()
usage_hits = []
model_hits = []


def scan(obj, path="", depth=0):
    if depth > 7:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in ("usage", "usagestats") and isinstance(v, dict):
                usage_hits.append((path, v))
            if kl == "model" and isinstance(v, str):
                model_hits.append(v)
            if any(s in kl for s in ("cost", "price", "billing")):
                usage_hits.append((path + "/" + k, v))
            scan(v, path + "/" + str(k), depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:6]):
            scan(v, f"{path}[{i}]", depth + 1)


for line in lines:
    try:
        rec = json.loads(line)
    except ValueError:
        continue
    if isinstance(rec, dict):
        kinds[rec.get("type") or rec.get("kind") or "?"] += 1
        scan(rec)

print("\nrecord kinds:", dict(kinds.most_common(12)))
print("models seen :", Counter(model_hits).most_common(6))

print(f"\nusage/cost candidates: {len(usage_hits)}")
seen = set()
for path, val in usage_hits[-8:]:
    key = path
    if key in seen:
        continue
    seen.add(key)
    text = json.dumps(val, ensure_ascii=False)[:400] if not isinstance(val, str) else val[:400]
    print(f"  {path[:90]}\n     {text}")
