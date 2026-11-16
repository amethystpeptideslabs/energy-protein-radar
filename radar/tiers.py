"""Tier classification. Pure functions on Decimal prices; no model involvement."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from .util import cents, money

STEAL, HOT, SOLID, SKIP, UNRATED = "STEAL", "HOT", "SOLID", "SKIP", "UNRATED"
TIER_EMOJI = {STEAL: "🚨", HOT: "🔥", SOLID: "✅", SKIP: "❌", UNRATED: "❔"}
TIER_RANK = {STEAL: 0, HOT: 1, SOLID: 2, SKIP: 3, UNRATED: 4}
RECORD_BADGE = "🏆"
UNVERIFIED_BADGE = "⚠️"


def tier_label(tier: str) -> str:
    return f"{TIER_EMOJI[tier]} {tier}"


def energy_thresholds(size_oz: float, cfg: dict[str, Any]) -> dict[str, Decimal]:
    rows = cfg["by_size"]
    key = str(int(size_oz)) if float(size_oz).is_integer() else str(size_oz)
    if key in rows:
        return {k: money(v) for k, v in rows[key].items()}
    base = rows[str(cfg.get("base_size_oz", 16))]
    scale = money(size_oz) / money(cfg.get("base_size_oz", 16))
    return {k: cents(money(v) * scale) for k, v in base.items()}


def energy_tier(unit_price: Any, size_oz: float, cfg: dict[str, Any]) -> str:
    """unit_price = cents-rounded $/can incl. CRV. STEAL < steal; HOT <= hot; SOLID <= solid."""
    p = cents(unit_price)
    t = energy_thresholds(size_oz, cfg)
    if p < t["steal"]:
        return STEAL
    if p <= t["hot"]:
        return HOT
    if p <= t["solid"]:
        return SOLID
    return SKIP


def protein_tier(pct_of_ref: Any | None, cfg: dict[str, Any]) -> str:
    if pct_of_ref is None:
        return UNRATED
    pct = money(pct_of_ref)
    if pct <= money(cfg["steal_pct"]):
        return STEAL
    if pct <= money(cfg["hot_pct"]):
        return HOT
    if pct <= money(cfg["solid_pct"]):
        return SOLID
    return SKIP


def protein_value_badge(per_10g: Any | None, bands: list[dict[str, Any]]) -> str:
    if per_10g is None:
        return ""
    v = money(per_10g)
    for band in bands:
        if v <= money(band["max"]):
            return band["badge"]
    return bands[-1]["badge"]


def is_hot_plus(tier: str) -> bool:
    return tier in (STEAL, HOT)
