"""DSH usage data layer.

Reads the two authoritative files DSH already maintains:

* ``usage-ledger.json``      per-day / per-provider / per-model token counts and
  cost (already priced by DSH, in the provider's currency).
* ``provider-snapshots.json`` live account balance + a spend counter that DSH
  accrues from balance drops.

The "current model" comes from the profile's ``cordis.patch.yml`` (the user's own
override layer, applied after the bundle), falling back to the bundled
``cordis.yml``.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

DSH_HOME = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
USAGE_DIR = DSH_HOME / "dsh-usage"
LEDGER = USAGE_DIR / "usage-ledger.json"
SNAPSHOTS = USAGE_DIR / "provider-snapshots.json"
PROFILE_DIR = Path(os.environ.get("DSH_PROFILE_DIR", DSH_HOME / "profiles" / "desktop"))


@dataclass
class ModelRef:
    provider: str = ""
    model: str = ""
    reasoning_effort: str = ""
    source: str = ""

    @property
    def display(self) -> str:
        return self.model or "(未知模型)"


@dataclass
class Usage:
    """Aggregated usage snapshot."""

    model: ModelRef = field(default_factory=ModelRef)
    today_cost: float = 0.0
    today_calls: int = 0
    today_tokens_in: int = 0
    today_tokens_out: int = 0
    today_cache_read: int = 0
    today_models: list[tuple[str, float]] = field(default_factory=list)
    total_cost: float = 0.0
    total_calls: int = 0
    first_day: str = ""
    last_day: str = ""
    currency: str = "CNY"
    balance: float | None = None
    balance_currency: str = "CNY"
    balance_updated: float = 0.0
    spend_watch_cny: float = 0.0
    ok: bool = True
    error: str = ""
    stamp: float = 0.0


def _read_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError):
        return None


def _find_model_config(path: Path, target_id: str = "agent-default-model"):
    """Line-oriented parse of a cordis YAML layer for one entry's config block."""
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


def read_current_model() -> ModelRef:
    """Current default model from the profile override layer, then the bundle."""
    for path, source in (
        (PROFILE_DIR / "cordis.patch.yml", "profile"),
        (PROFILE_DIR / "cordis.yml", "bundle"),
    ):
        cfg = _find_model_config(path)
        if cfg and cfg.get("model"):
            return ModelRef(
                provider=cfg.get("provider", ""),
                model=cfg["model"],
                reasoning_effort=cfg.get("reasoningEffort", ""),
                source=source,
            )
    return ModelRef()


def _today_key(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts if ts else time.time()))


def load_usage() -> Usage:
    """Build the current usage snapshot from DSH's own accounting files."""
    u = Usage(stamp=time.time())
    u.model = read_current_model()

    ledger = _read_json(LEDGER)
    if ledger is None:
        u.ok = False
        u.error = f"读不到用量账本: {LEDGER}"
    else:
        days: dict = ledger.get("days", {}) or {}
        today = _today_key()
        for day in sorted(days):
            per_provider = days[day] or {}
            day_cost = 0.0
            for provider, per_model in per_provider.items():
                for model, rec in (per_model or {}).items():
                    cost = float(rec.get("cost", 0.0) or 0.0)
                    calls = int(rec.get("calls", 0) or 0)
                    u.total_cost += cost
                    u.total_calls += calls
                    day_cost += cost
                    if not u.first_day:
                        u.first_day = day
                    u.last_day = day
                    if day == today:
                        u.today_cost += cost
                        u.today_calls += calls
                        u.today_tokens_in += int(rec.get("inputTokens", 0) or 0)
                        u.today_tokens_out += int(rec.get("outputTokens", 0) or 0)
                        u.today_cache_read += int(rec.get("cacheReadTokens", 0) or 0)
                        u.today_models.append((model, cost))
        u.today_models.sort(key=lambda x: -x[1])

    snaps = _read_json(SNAPSHOTS)
    if snaps:
        watch = snaps.get("spendWatch") or {}
        u.spend_watch_cny = float(watch.get("accruedCny", 0.0) or 0.0)
        best = None
        for provider, rec in (snaps.get("providers") or {}).items():
            bal = rec.get("balance") or {}
            if bal.get("totalBalance") is None:
                continue
            if provider == u.model.provider:
                best = (rec, bal)
                break
            if best is None:
                best = (rec, bal)
        if best:
            rec, bal = best
            try:
                u.balance = float(bal.get("totalBalance"))
            except (TypeError, ValueError):
                u.balance = None
            u.balance_currency = bal.get("currency", "CNY")
            u.balance_updated = float(bal.get("updatedAt", 0) or 0) / 1000.0
    return u


@dataclass
class AccountBalance:
    """Just the account balance: the one figure the session logs cannot give."""

    balance: float | None = None
    currency: str = "CNY"
    updated: float = 0.0
    provider: str = ""

    @property
    def stale_seconds(self) -> float:
        return max(0.0, time.time() - self.updated) if self.updated else 0.0


def load_account(prefer_provider: str = "") -> AccountBalance:
    """Balance from ``provider-snapshots.json`` (refreshed only by DSH itself)."""
    snap = _read_json(SNAPSHOTS)
    out = AccountBalance()
    if not snap:
        return out
    providers = snap.get("providers") or {}
    chosen = None
    if prefer_provider and prefer_provider in providers:
        chosen = providers[prefer_provider]
    if chosen is None or (chosen.get("balance") or {}).get("totalBalance") is None:
        for rec in providers.values():
            if (rec.get("balance") or {}).get("totalBalance") is not None:
                chosen = rec
                break
    if not chosen:
        return out
    bal = chosen.get("balance") or {}
    try:
        out.balance = float(bal.get("totalBalance"))
    except (TypeError, ValueError):
        out.balance = None
    out.currency = bal.get("currency", "CNY")
    out.updated = float(bal.get("updatedAt", 0) or 0) / 1000.0
    out.provider = chosen.get("provider", "")
    return out


def resolve_active_model(u: Usage, now: float | None = None) -> ModelRef:
    """Best guess at the model actually in use, from the stale ledger.

    Kept for the ledger-based path; the pet itself reads the model from the
    session logs (:mod:`pet.liveusage`), which is authoritative in real time.

    The configured default is authoritative, but a session can switch models
    mid-conversation (that is what the GUI model picker does), so if today's
    ledger shows a *different* model being used we report that one instead.
    """
    now = now or time.time()
    if not u.today_models:
        return u.model
    if u.model.model and any(m == u.model.model for m, _ in u.today_models):
        return u.model
    # ledger has no record of the configured model today -> a switch happened
    top_model, _cost = u.today_models[0]
    if top_model and top_model != u.model.model:
        return ModelRef(u.model.provider, top_model, u.model.reasoning_effort, "ledger")
    return u.model


def format_money(value: float | None, currency: str = "CNY") -> str:
    if value is None:
        return "--"
    symbol = {"CNY": "¥", "USD": "$", "EUR": "€"}.get(currency, "")
    if value >= 1000:
        return f"{symbol}{value:,.0f}"
    if value >= 100:
        return f"{symbol}{value:.1f}"
    return f"{symbol}{value:.2f}"


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def demo_usage() -> Usage:
    """Plausible values for a screenshot/tryout when DSH data is unavailable."""
    u = Usage(stamp=time.time(), ok=True)
    u.model = ModelRef("deepseek-official", "deepseek-v4-flash", "max", "demo")
    u.today_cost = 1.87
    u.today_calls = 43
    u.today_tokens_in = 184_320
    u.today_tokens_out = 21_660
    u.today_cache_read = 2_310_000
    u.today_models = [("deepseek-v4-flash", 1.87)]
    u.total_cost = 26.43
    u.total_calls = 1_204
    u.first_day = u.last_day = time.strftime("%Y-%m-%d")
    u.balance = 55.84
    u.balance_currency = "CNY"
    u.balance_updated = time.time()
    u.spend_watch_cny = 12.39
    return u


if __name__ == "__main__":  # quick manual check
    snap = load_usage()
    active = resolve_active_model(snap)
    print("configured :", snap.model)
    print("active     :", active)
    print("today cost :", format_money(snap.today_cost, snap.currency), f"({snap.today_calls} calls)")
    print("total cost :", format_money(snap.total_cost, snap.currency), f"({snap.total_calls} calls)")
    print("balance    :", format_money(snap.balance, snap.balance_currency))
    print("spend watch:", format_money(snap.spend_watch_cny, "CNY"))
    print("days       :", snap.first_day, "->", snap.last_day)
    print("today split:", snap.today_models)
    print("ok         :", snap.ok, snap.error)
