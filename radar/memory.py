"""Persistent state: data/memory.json (agent state), data/history.json (daily best per
product, kept forever), data/offers.json (raw validated offers, pruned at 90 days)."""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Config
from .pricing import regular_unit_price
from .util import cents, iso_now, now_local, parse_date, read_json, write_json, write_text

SCHEMA_VERSION = 2


def empty_memory() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "calibrated_at": None,
        "products": {},
        "dead_codes": [],
        "active_codes": [],
        "alerts_sent": [],
        "latest_run": {"date": "", "mode": "", "status": "", "cost_usd": 0.0, "searches": 0},
        "cost_ledger": {},
        "budget_warning_month": None,
    }


def empty_product_mem() -> dict[str, Any]:
    return {
        "ref_unit_price": None,
        "ref_updated": None,
        "ref_source": "seed",
        "protein_verified": None,
        "size_verified": None,
        "all_time_low": None,
        "last_best": None,
        "trend_30d": "flat",
    }


@dataclass
class State:
    data_dir: Path
    memory: dict[str, Any]
    history: dict[str, list[list[Any]]]
    offers: list[dict[str, Any]]
    latest: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, data_dir: Path, cfg: Config) -> "State":
        mem = read_json(data_dir / "memory.json", None) or empty_memory()
        for k, v in empty_memory().items():
            mem.setdefault(k, v)
        for pid, p in cfg.products.items():
            pm = mem["products"].setdefault(pid, empty_product_mem())
            for k, v in empty_product_mem().items():
                pm.setdefault(k, v)
            if pm["ref_unit_price"] is None and p.ref_unit_price is not None:
                pm["ref_unit_price"] = p.ref_unit_price
                pm["ref_source"] = "seed"
        return cls(data_dir=data_dir, memory=mem,
                   history=read_json(data_dir / "history.json", {}) or {},
                   offers=read_json(data_dir / "offers.json", []) or [],
                   latest=read_json(data_dir / "latest.json", {}) or {})

    def apply_overrides(self, cfg: Config) -> None:
        """Calibrated refs / verified label values override YAML seeds at runtime."""
        for pid, p in cfg.products.items():
            pm = self.memory["products"].get(pid, {})
            if pm.get("ref_unit_price") is not None:
                p.ref_unit_price = float(pm["ref_unit_price"])
            if pm.get("protein_verified"):
                p.protein_g = float(pm["protein_verified"]["value"])
            if pm.get("size_verified"):
                p.unit_size_oz = float(pm["size_verified"]["value"])

    def save(self, *, write_latest: bool = True) -> None:
        write_json(self.data_dir / "memory.json", self.memory)
        lines = [f'  "{pid}": ' + _compact(rows) for pid, rows in sorted(self.history.items())]
        write_text(self.data_dir / "history.json", "{\n" + ",\n".join(lines) + "\n}\n")
        write_json(self.data_dir / "offers.json", self.offers, indent=None)
        if write_latest and self.latest:
            write_json(self.data_dir / "latest.json", self.latest, indent=None)


def _compact(rows: list[list[Any]]) -> str:
    import json
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))


# ------------------------------------------------------------------ offers archive
def merge_offers(state: State, new: list[dict[str, Any]], cfg: Config, today: date) -> None:
    """Adds this run's validated offers; prunes raw offers older than retention."""
    stamp = iso_now()
    for o in new:
        o["seen_at"] = stamp
        o["seen_date"] = today.isoformat()
    state.offers.extend(new)
    keep_days = int(cfg.settings["history"]["raw_offer_retention_days"])
    cutoff = (today - timedelta(days=keep_days)).isoformat()
    state.offers = [o for o in state.offers if o.get("seen_date", "") >= cutoff]


def current_offers(state: State, cfg: Config, today: date) -> list[dict[str, Any]]:
    """Latest observation of each offer seen within the carry-over window, not expired."""
    window = int(cfg.settings["research"]["offer_carryover_days"])
    cutoff = (today - timedelta(days=window)).isoformat()
    latest: dict[tuple, dict[str, Any]] = {}
    for o in state.offers:
        if o.get("seen_date", "") < cutoff:
            continue
        if o["product_id"] not in cfg.products or not cfg.products[o["product_id"]].enabled:
            continue
        ends = parse_date(o.get("ends"))
        if ends and ends < today:
            continue
        starts = parse_date(o.get("starts"))
        if starts and starts > today:   # not live yet
            continue
        fp = (o["product_id"], o.get("retailer_key"), o.get("source_url"), (o.get("code") or "").upper(),
              o.get("pack_count"))
        if fp not in latest or o.get("seen_at", "") >= latest[fp].get("seen_at", ""):
            latest[fp] = o
    return list(latest.values())


# ------------------------------------------------------------------ records & history
def detect_records(state: State, best_by_product: dict[str, dict[str, Any]],
                   today: date) -> list[dict[str, Any]]:
    """A record is a strictly lower effective unit price than the stored all-time low.
    The first observation sets a baseline silently (no badge). UNVERIFIED never counts."""
    records = []
    for pid, o in best_by_product.items():
        if o.get("unverified"):
            continue
        pm = state.memory["products"][pid]
        atl = pm.get("all_time_low")
        entry = {"unit_price": o["unit_price"], "retailer": o.get("retailer_name", ""),
                 "date": today.isoformat(), "url": o["source_url"], "code": o.get("code") or None}
        if not atl:
            pm["all_time_low"] = entry
            o["is_record"] = False
        elif o["unit_price"] < float(atl["unit_price"]):
            o["previous_record"] = dict(atl)
            pm["all_time_low"] = entry
            o["is_record"] = True
            records.append(o)
        else:
            o["is_record"] = False
    return records


def update_history(state: State, best_by_product: dict[str, dict[str, Any]], today: date) -> None:
    d = today.isoformat()
    for pid, o in best_by_product.items():
        if o.get("unverified"):
            continue
        rows = state.history.setdefault(pid, [])
        row = [d, o["unit_price"], o["tier"], o.get("retailer_name", "")]
        if rows and rows[-1][0] == d:
            if o["unit_price"] <= rows[-1][1]:
                rows[-1] = row
        else:
            rows.append(row)
        pm = state.memory["products"][pid]
        pm["last_best"] = {"unit_price": o["unit_price"], "tier": o["tier"], "date": d}
        pm["trend_30d"] = trend_30d(rows, today)


def trend_30d(rows: list[list[Any]], today: date) -> str:
    cutoff = (today - timedelta(days=30)).isoformat()
    recent = [r for r in rows if r[0] >= cutoff]
    if len(recent) < 4:
        return "flat"
    half = len(recent) // 2
    a = statistics.mean(r[1] for r in recent[:half])
    b = statistics.mean(r[1] for r in recent[half:])
    if a == 0:
        return "flat"
    change = (b - a) / a
    return "down" if change < -0.03 else "up" if change > 0.03 else "flat"


# ------------------------------------------------------------------ calibration
def calibrate(state: State, cfg: Config, raw_offers: list[dict[str, Any]],
              today: date) -> list[dict[str, Any]]:
    """Sets ref_unit_price = median REGULAR per-unit price across retailers (never from
    sale prices) and verifies label protein / size. Returns a list of corrections."""
    corrections: list[dict[str, Any]] = []
    by_pid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for o in raw_offers:
        by_pid[o["product_id"]].append(o)
    for pid, offers in by_pid.items():
        p = cfg.products[pid]
        pm = state.memory["products"][pid]
        per_retailer: dict[str, list[float]] = defaultdict(list)
        for o in offers:
            reg = regular_unit_price(o)
            if reg is not None and reg > 0:
                per_retailer[o.get("retailer_key", "?")].append(float(reg))
        points = [statistics.median(v) for v in per_retailer.values()]
        min_points = 1 if (p.ref_unit_price is None or p.needs_verification) else 2
        if len(points) >= min_points:
            new_ref = float(cents(statistics.median(points)))
            old = pm.get("ref_unit_price")
            if old is None or abs(new_ref - float(old)) >= 0.01:
                corrections.append({"product_id": pid, "field": "ref_unit_price", "old": old,
                                    "new": new_ref, "basis": f"median regular price, {len(points)} retailers"})
            pm.update(ref_unit_price=new_ref, ref_updated=today.isoformat(),
                      ref_source=f"calibrated ({len(points)} retailers)")
        labels = [round(float(o["label_protein_g"]), 1) for o in offers
                  if float(o.get("label_protein_g") or 0) > 0]
        if labels and p.protein_g:
            value, n = Counter(labels).most_common(1)[0]
            src = next(o["source_url"] for o in offers if round(float(o.get("label_protein_g") or 0), 1) == value)
            pm["protein_verified"] = {"value": value, "source_url": src, "date": today.isoformat(), "n": n}
            if abs(value - p.protein_g) >= 0.5:
                corrections.append({"product_id": pid, "field": "protein_g", "old": p.protein_g,
                                    "new": value, "basis": f"label, {n} source(s)"})
        if p.needs_verification:
            sizes = [round(float(o["unit_size_oz"]), 1) for o in offers if float(o.get("unit_size_oz") or 0) > 0]
            if sizes:
                value, n = Counter(sizes).most_common(1)[0]
                pm["size_verified"] = {"value": value, "date": today.isoformat(), "n": n}
                if abs(value - p.unit_size_oz) >= 0.3:
                    corrections.append({"product_id": pid, "field": "unit_size_oz", "old": p.unit_size_oz,
                                        "new": value, "basis": f"listing size, {n} source(s)"})
    state.memory["calibrated_at"] = today.isoformat()
    return corrections


# ------------------------------------------------------------------ codes & alerts
def add_dead_codes(state: State, entries: list[dict[str, Any]]) -> None:
    existing = {(d["code"].upper(), d.get("retailer", "")) for d in state.memory["dead_codes"]}
    for e in entries:
        if (e["code"].upper(), e["retailer"]) not in existing:
            state.memory["dead_codes"].append(e)
    dead = {(d["code"].upper(), d.get("retailer", "")) for d in state.memory["dead_codes"]}
    state.memory["active_codes"] = [c for c in state.memory["active_codes"]
                                    if (c["code"].upper(), c.get("retailer", "")) not in dead]


def prune_codes(state: State, today: date) -> None:
    state.memory["dead_codes"] = [d for d in state.memory["dead_codes"]
                                  if (parse_date(d.get("skip_until")) or today) >= today - timedelta(days=30)]


def record_active_codes(state: State, offers: list[dict[str, Any]], today: date) -> None:
    seen = {(c["code"].upper(), c.get("retailer", "")) for c in state.memory["active_codes"]}
    for o in offers:
        code = (o.get("code") or "").strip()
        if not code or (code.upper(), o["retailer_key"]) in seen:
            continue
        seen.add((code.upper(), o["retailer_key"]))
        state.memory["active_codes"].append({
            "code": code, "retailer": o["retailer_key"], "source_url": o["source_url"],
            "reported_on": o.get("evidence_date") or today.isoformat(), "expires": o.get("ends") or None})
    state.memory["active_codes"] = [c for c in state.memory["active_codes"]
                                    if not (parse_date(c.get("expires")) and parse_date(c["expires"]) < today)][-200:]


def alert_recently_sent(state: State, fingerprint: str, hours: int) -> bool:
    cutoff = now_local() - timedelta(hours=hours)
    for a in state.memory["alerts_sent"]:
        if a["fingerprint"] == fingerprint:
            try:
                if datetime.fromisoformat(a["sent_at"]) >= cutoff:
                    return True
            except ValueError:
                continue
    return False


def remember_alert(state: State, fingerprint: str, priority: int) -> None:
    state.memory["alerts_sent"].append({"fingerprint": fingerprint, "sent_at": iso_now(), "priority": priority})
    cutoff = now_local() - timedelta(days=14)
    kept = []
    for a in state.memory["alerts_sent"]:
        try:
            if datetime.fromisoformat(a["sent_at"]) >= cutoff:
                kept.append(a)
        except ValueError:
            pass
    state.memory["alerts_sent"] = kept
