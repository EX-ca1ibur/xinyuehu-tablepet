"""Live usage: the same numbers DSH's own GUI shows, read from session logs.

Why not ``usage-ledger.json``: on this machine that file is only written at
certain points (its mtime can be a day older than the last activity), so a pet
driven by it shows a frozen amount. The session logs under
``$DSH_HOME/sessions/<cwd>/<session>/session.v4.jsonl.zstd`` are appended to on
every step, and each ``assistant/message`` carries that call's real token usage
plus its timestamp.

Cost is computed with the *same* formula and price book DSH ships
(``@linxin666/dsh-usage/src/core/pricing.ts``), priced per call at that call's
own billing period:

    spend = (cacheRead * cacheHit
             + (input + cacheWrite) * inputMiss
             + output * output) / 1e6

Peak = Beijing time, Mon-Fri 09:00-12:00 and 14:00-18:00; everything else is
off-peak at half price. Verified against the ledger: off-peak rows reproduce
the stored cost to the last micro-CNY.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import zstandard as zstd
except ImportError:  # pragma: no cover - optional dependency
    zstd = None

DSH_HOME = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
SESSIONS_DIR = DSH_HOME / "sessions"
CURATED_DIR = DSH_HOME / "storages" / "session_projcache_archive_manager_v2" / "sessions"

BEIJING_OFFSET_MS = 8 * 3_600_000
PEAK_WINDOWS = ((9 * 60, 12 * 60), (14 * 60, 18 * 60))
V4_PRO_FOLDED_INTO_FLASH_AT_MS = _dt.datetime(2026, 9, 14, 12, 0,
                                              tzinfo=_dt.timezone.utc).timestamp() * 1000

# CNY per million tokens: (offPeak, peak)
FLASH_PRICE = {"cacheHit": (0.02, 0.04), "inputMiss": (1.0, 2.0), "output": (4.0, 8.0)}
PRO_PRICE = {"cacheHit": (0.15, 0.30), "inputMiss": (4.5, 9.0), "output": (13.5, 27.0)}

MAX_PARSE_BYTES = 64 * 1024 * 1024


def is_peak(at_ms: float) -> bool:
    shifted = _dt.datetime.fromtimestamp(at_ms / 1000.0, tz=_dt.timezone.utc) + \
        _dt.timedelta(milliseconds=BEIJING_OFFSET_MS)
    if shifted.weekday() > 4:
        return False
    minute = shifted.hour * 60 + shifted.minute
    return any(lo <= minute < hi for lo, hi in PEAK_WINDOWS)


def price_row(model: str, at_ms: float):
    if "v4-pro" in model and at_ms < V4_PRO_FOLDED_INTO_FLASH_AT_MS:
        return PRO_PRICE
    return FLASH_PRICE


def call_spend(model: str, usage: dict, at_ms: float) -> float:
    row = price_row(model, at_ms)
    col = 1 if is_peak(at_ms) else 0
    tokens = (
        int(usage.get("cacheReadTokens", 0) or 0) * row["cacheHit"][col]
        + (int(usage.get("inputTokens", 0) or 0) + int(usage.get("cacheWriteTokens", 0) or 0))
        * row["inputMiss"][col]
        + int(usage.get("outputTokens", 0) or 0) * row["output"][col]
    )
    return tokens / 1_000_000.0


@dataclass
class SessionUsage:
    path: Path
    session_id: str = ""
    model: str = ""
    provider: str = ""
    effort: str = ""
    context_window: int = 0
    calls: int = 0
    spend: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cache_read: int = 0
    last_ms: float = 0.0
    last_usage: dict = field(default_factory=dict)
    mtime: float = 0.0
    size: int = 0
    by_model: dict = field(default_factory=dict)
    today_spend: float = 0.0
    today_calls: int = 0


@dataclass
class LiveUsage:
    today_spend: float = 0.0
    today_calls: int = 0
    total_spend: float = 0.0
    total_calls: int = 0
    session_spend: float = 0.0
    session_calls: int = 0
    model: str = ""
    provider: str = ""
    effort: str = ""
    context_tokens: int = 0
    context_window: int = 0
    session_id: str = ""
    sessions_seen: int = 0
    by_model: dict = field(default_factory=dict)
    ok: bool = True
    error: str = ""
    stamp: float = 0.0

    @property
    def context_pct(self) -> float:
        if self.context_window <= 0:
            return 0.0
        return min(100.0, 100.0 * self.context_tokens / self.context_window)

    def balance_key(self) -> tuple:
        if not self.by_model:
            return ()
        return (self.model, round(self.session_spend, 4),
                sorted(self.by_model.items())[0][0])


class LiveUsageReader:
    """Parses session logs, caching per file so polling stays cheap."""

    def __init__(self, sessions_dir: Path = SESSIONS_DIR):
        self.sessions_dir = Path(sessions_dir)
        self._cache: dict[Path, tuple[float, int, SessionUsage]] = {}
        self._lock = threading.Lock()
        self._busy = False

    # ------------------------------------------------------------------ parsing
    def _log_paths(self) -> list[Path]:
        if not self.sessions_dir.exists():
            return []
        return sorted(self.sessions_dir.rglob("*.jsonl.zstd"),
                      key=lambda p: p.stat().st_mtime, reverse=True)

    def _parse(self, path: Path) -> SessionUsage:
        out = SessionUsage(path=path, session_id=path.parent.name)
        st = path.stat()
        out.mtime, out.size = st.st_mtime, st.st_size
        if zstd is None or st.st_size > MAX_PARSE_BYTES:
            return out
        try:
            with path.open("rb") as fh:
                raw = zstd.ZstdDecompressor().stream_reader(fh).read()
        except (OSError, zstd.ZstdError):
            return out

        # A session can switch model mid-flight (the GUI picker does exactly
        # that), so every declaration is recorded in order and each call is
        # priced under the model that was in force at that moment.
        timeline: list[tuple[float, str]] = []
        active_model = ""
        today = _dt.date.today()
        for line in raw.decode("utf-8", errors="replace").splitlines():
            if not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            kind = rec.get("type")
            at = float(rec.get("time") or 0.0)
            if kind == "request/context":
                data = rec.get("data") or {}
                out.provider = data.get("provider", out.provider) or out.provider
                cw = data.get("contextWindow")
                if isinstance(cw, int) and cw > 0:
                    out.context_window = cw
                model = data.get("model")
                if model and model != active_model:
                    active_model = str(model)
                    timeline.append((at, active_model))
            elif kind == "request/header":
                cfg = ((rec.get("data") or {}).get("header") or {}).get("config") or {}
                out.provider = cfg.get("provider", out.provider) or out.provider
                out.effort = cfg.get("reasoningEffort", out.effort) or out.effort
                model = cfg.get("model")
                if model and model != active_model:
                    active_model = str(model)
                    timeline.append((at, active_model))
            elif kind == "assistant/message":
                data = rec.get("data") or {}
                usage = data.get("usage")
                if not isinstance(usage, dict):
                    continue
                model = self._model_at(timeline, at) or "deepseek-flash"
                spend = call_spend(model, usage, at)
                out.calls += 1
                out.spend += spend
                entry = out.by_model.setdefault(model, {"calls": 0, "spend": 0.0})
                entry["calls"] += 1
                entry["spend"] += spend
                if at and _dt.datetime.fromtimestamp(at / 1000.0).date() == today:
                    out.today_spend += spend
                    out.today_calls += 1
                out.tokens_in += int(usage.get("inputTokens", 0) or 0)
                out.tokens_out += int(usage.get("outputTokens", 0) or 0)
                out.tokens_cache_read += int(usage.get("cacheReadTokens", 0) or 0)
                if at >= out.last_ms:
                    out.last_ms = at
                    out.last_usage = usage

        if timeline:
            out.model = timeline[-1][1]
        if not out.model:
            out.model = self._model_from_projection(out.session_id)
        return out

    @staticmethod
    def _model_at(timeline: list[tuple[float, str]], at: float) -> str:
        """The model in force at `at` (declarations are ordered by time)."""
        if not timeline:
            return ""
        current = timeline[0][1]
        for ts, model in timeline:
            if ts <= at:
                current = model
            else:
                break
        return current

    def _model_from_projection(self, session_id: str) -> str:
        """Fallback: the projection cache records modelSelection.lastUsed."""
        if not CURATED_DIR.exists():
            return ""
        for f in CURATED_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows = (data.get("record") or {}).get("rows") or {}
            sel = (rows.get("modelSelection") or {}).get("val") or {}
            last = (sel.get("lastUsed") or {}).get("model")
            if last:
                return str(last)
        return ""

    def _session_of(self, path: Path) -> SessionUsage:
        st = path.stat()
        hit = self._cache.get(path)
        if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
            return hit[2]
        parsed = self._parse(path)
        self._cache[path] = (parsed.mtime, parsed.size, parsed)
        return parsed

    # ----------------------------------------------------------------- snapshot
    def snapshot(self, session_id: str | None = None) -> LiveUsage:
        out = LiveUsage(stamp=time.time())
        sid = session_id or os.environ.get("DSH_SESSION_ID", "")
        try:
            paths = self._log_paths()
        except OSError as exc:
            out.ok, out.error = False, str(exc)
            return out
        if not paths:
            out.ok, out.error = False, f"没有找到会话日志: {self.sessions_dir}"
            return out

        today = _dt.date.today()
        current: SessionUsage | None = None
        for path in paths:
            try:
                parsed = self._session_of(path)
            except OSError:
                continue
            out.sessions_seen += 1
            out.total_spend += parsed.spend
            out.total_calls += parsed.calls
            out.today_spend += parsed.today_spend
            out.today_calls += parsed.today_calls
            for model, agg in parsed.by_model.items():
                slot = out.by_model.setdefault(model, {"calls": 0, "spend": 0.0})
                slot["calls"] += agg["calls"]
                slot["spend"] += agg["spend"]
            if sid and parsed.session_id == sid:
                current = parsed
        if current is None:
            current = self._session_of(paths[0])

        out.session_spend = current.spend
        out.session_calls = current.calls
        out.model = current.model
        out.provider = current.provider
        out.effort = current.effort
        out.session_id = current.session_id
        out.context_window = current.context_window
        # live context size = the prompt actually sent on the most recent call
        last = current.last_usage or {}
        out.context_tokens = int(last.get("inputTokens", 0) or 0) + \
            int(last.get("cacheReadTokens", 0) or 0) + \
            int(last.get("cacheWriteTokens", 0) or 0)
        if not out.model:
            out.ok, out.error = False, "会话日志里没读到模型"
        return out


def demo_live() -> LiveUsage:
    """Plausible live numbers for screenshots when no session log is readable."""
    return LiveUsage(
        today_spend=4.4048, today_calls=436,
        total_spend=8.7673, total_calls=1062,
        session_spend=4.0496, session_calls=405,
        model="deepseek-flash", provider="deepseek-official", effort="max",
        context_tokens=401_489, context_window=1_000_000,
        session_id="session-demo", sessions_seen=12,
        by_model={"deepseek-flash": {"calls": 858, "spend": 7.0058}},
    )


if __name__ == "__main__":  # manual check
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    reader = LiveUsageReader()
    started = time.time()
    snap = reader.snapshot()
    cold = time.time() - started
    started = time.time()
    reader.snapshot()
    warm = time.time() - started
    print(f"model        : {snap.model} ({snap.provider}) effort={snap.effort or '-'}")
    print(f"session      : {snap.session_id}  calls={snap.session_calls}  spend=¥{snap.session_spend:.4f}")
    print(f"today        : ¥{snap.today_spend:.4f} over {snap.today_calls} calls")
    print(f"total (all)  : ¥{snap.total_spend:.4f} over {snap.total_calls} calls")
    print(f"context      : {snap.context_tokens:,} / {snap.context_window:,} = {snap.context_pct:.1f}%")
    print(f"sessions seen: {snap.sessions_seen}   ok={snap.ok} {snap.error}")
    print(f"timing       : cold {cold*1000:.0f} ms, warm {warm*1000:.0f} ms")
    print("spend by model:")
    for model, agg in sorted(snap.by_model.items(), key=lambda kv: -kv[1]["spend"]):
        print(f"  {model:22s} {agg['calls']:5d} calls  ¥{agg['spend']:.4f}")
