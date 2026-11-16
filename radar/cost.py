"""Token + web-search cost tracking from real API `usage`, and budget enforcement."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


class BudgetExceeded(RuntimeError):
    pass


def _get(obj: Any, name: str, default: Any = 0) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


@dataclass
class CostTracker:
    prices: dict[str, Any]
    max_run_usd: float = 999.0
    usd: float = 0.0
    searches: int = 0
    calls: int = 0
    tokens: dict[str, int] = field(default_factory=lambda: {
        "input": 0, "output": 0, "cache_write": 0, "cache_read": 0})

    def price_for(self, model: str, prompt_tokens: int) -> dict[str, float]:
        table = self.prices.get(model)
        if table is None:  # unknown model: assume the most expensive we know (never under-count)
            table = max((v for k, v in self.prices.items() if isinstance(v, dict) and "input" in v),
                        key=lambda v: v["input"])
        threshold = table.get("long_prompt_threshold")
        if threshold and prompt_tokens > threshold and "long" in table:
            return table["long"]
        return table

    def add_usage(self, model: str, usage: Any) -> float:
        inp = int(_get(usage, "input_tokens") or 0)
        out = int(_get(usage, "output_tokens") or 0)
        cw = int(_get(usage, "cache_creation_input_tokens") or 0)
        cr = int(_get(usage, "cache_read_input_tokens") or 0)
        stu = _get(usage, "server_tool_use", None)
        n_search = int(_get(stu, "web_search_requests") or 0) if stu is not None else 0
        t = self.price_for(model, inp + cw + cr)
        usd = (inp * t["input"] + out * t["output"] + cw * t.get("cache_write_5m", t["input"] * 1.25)
               + cr * t.get("cache_read", t["input"] * 0.1)) / 1_000_000
        usd += n_search * float(self.prices["web_search_per_1k"]) / 1000
        self.usd += usd
        self.searches += n_search
        self.calls += 1
        for k, v in (("input", inp), ("output", out), ("cache_write", cw), ("cache_read", cr)):
            self.tokens[k] += v
        if self.usd > self.max_run_usd:
            raise BudgetExceeded(f"run cost ${self.usd:.2f} passed the per-run cap ${self.max_run_usd:.2f}")
        return usd


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def month_spend(memory: dict[str, Any], d: date) -> float:
    return float(memory.get("cost_ledger", {}).get(month_key(d), {}).get("usd", 0.0))


def budget_state(memory: dict[str, Any], d: date, cap: float, downgrade_pct: float) -> str:
    """'ok' | 'downgrade' (>= downgrade_pct of cap) | 'exhausted' (>= 100%)."""
    if cap <= 0:
        return "ok"
    spent = month_spend(memory, d)
    if spent >= cap:
        return "exhausted"
    if spent >= cap * downgrade_pct / 100:
        return "downgrade"
    return "ok"


def record_run(memory: dict[str, Any], d: date, tracker: CostTracker) -> None:
    ledger = memory.setdefault("cost_ledger", {})
    m = ledger.setdefault(month_key(d), {"usd": 0.0, "runs": 0, "searches": 0})
    m["usd"] = round(m["usd"] + tracker.usd, 4)
    m["runs"] += 1
    m["searches"] += tracker.searches
