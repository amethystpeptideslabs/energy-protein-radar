"""Run orchestration: mode selection -> research -> extraction -> validation -> pricing ->
records/history -> outputs (JSON for the app, Obsidian notes) -> push alerts -> cost ledger."""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import __version__
from .config import ROOT, Config, load_config
from .cost import BudgetExceeded, CostTracker, budget_state, month_key, month_spend, record_run
from .memory import (State, add_dead_codes, calibrate, current_offers, detect_records, merge_offers,
                     prune_codes, record_active_codes, update_history)
from .notify import plan_pushes, send
from .obsidian import write_vault
from .pricing import price_offer, rank_key
from .research import ResearchResult, Researcher, WebSearchDisabled, build_jobs, build_system
from .tiers import STEAL, is_hot_plus
from .util import iso_now, now_local, parse_date, read_json, today as today_fn, write_json
from .validate import dead_codes_from_reports, flag_unverified, validate_offers

log = logging.getLogger("radar")

SLIM_KEYS = ("product_id", "category", "retailer_name", "retailer_key", "source_url", "source_kind",
             "evidence_date", "pack_count", "pack_price", "packs_in_cart", "units_in_cart",
             "effective_pack_total", "unit_price", "price_per_oz", "price_per_10g_protein", "pct_vs_ref",
             "tier", "protein_value_badge", "is_record", "unverified", "code", "starts", "ends",
             "in_store_only", "membership_required", "limit_per_customer", "min_qty", "promo_type",
             "subscribe_save_pct", "seen_at", "is_case")


@dataclass
class RunOptions:
    mode: str = "auto"
    only: str | None = None
    dry_run: bool = False
    no_push: bool = False
    no_commit: bool = False
    root: Path = ROOT
    out: Path | None = None
    slot: str | None = None
    ingest: Path | None = None   # research JSON written by a Claude session (no API key needed)
    plan: bool = False           # print today's research plan as JSON and exit


@dataclass
class RunResult:
    mode: str
    slot: str
    status: str
    reason: str = ""
    cost_usd: float = 0.0
    searches: int = 0
    pushes: list[str] = field(default_factory=list)
    corrections: list[dict[str, Any]] = field(default_factory=list)
    products_with_offers: int = 0
    exit_code: int = 0


# ------------------------------------------------------------------ mode selection
def detect_slot(cfg: Config, explicit: str | None) -> str:
    if explicit:
        return explicit
    sched = (os.environ.get("DEAL_RADAR_SCHEDULE") or "").strip()
    if sched:
        return cfg.settings["schedule"]["crons"].get(sched, "manual")
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        return "manual"
    h = now_local().hour
    return "morning" if h < 11 else "midday" if h < 17 else "evening"


def in_deal_season(cfg: Config, d: date) -> bool:
    for w in cfg.settings["schedule"].get("deal_season", []):
        if parse_date(str(w["start"])) <= d <= parse_date(str(w["end"])):
            return True
    return False


def resolve_mode(cfg: Config, state: State, requested: str, slot: str, d: date) -> tuple[str, str]:
    """-> (mode, note). mode may be 'skip'."""
    if requested != "auto":
        return requested, ""
    if slot == "evening":
        return ("quick", "deal-season evening run") if in_deal_season(cfg, d) else \
            ("skip", "evening slot outside deal season: no API calls")
    if not state.memory.get("calibrated_at"):
        return "calibrate", "first run: calibrating refs and labels"
    if slot == "morning" and d.weekday() in cfg.settings["schedule"]["deep_weekdays"]:
        return "deep", ""
    return "quick", ""


# ------------------------------------------------------------------ helpers
def _anthropic_client(cfg: Config):
    import anthropic
    return anthropic.Anthropic(api_key=cfg.api_key, max_retries=5, timeout=600)


def _job_from_dict(fx: dict[str, Any]) -> tuple[ResearchResult, dict[str, Any]]:
    from .extract import OFFER_FIELDS
    from .util import normalize_url
    r = ResearchResult(label=str(fx.get("label", "job")), product_ids=list(fx.get("product_ids", [])),
                       dossier=fx.get("dossier", ""), searches=int(fx.get("searches", 0) or 0))
    r.urls = {normalize_url(u): u for u in fx.get("urls", []) if isinstance(u, str) and u}
    r.page_ages = {normalize_url(k): v for k, v in (fx.get("page_ages") or {}).items()}
    extraction = fx.get("extraction") or {"offers": fx.get("offers", []), "dead_codes": fx.get("dead_codes", [])}
    defaults = {k: ("" if v["type"] == "string" else 0 if v["type"] in ("number", "integer") else False)
                for k, v in OFFER_FIELDS.items()}
    defaults.update(promo_type="none", min_qty=1, pack_count=1)
    offers = [{**defaults, **{k: v for k, v in o.items() if v is not None}}
              for o in extraction.get("offers", []) if isinstance(o, dict)]
    return r, {"offers": offers, "dead_codes": extraction.get("dead_codes", []) or []}


def _fixture_jobs(root: Path) -> list[tuple[ResearchResult, dict[str, Any]]]:
    return [_job_from_dict(json.loads(f.read_text(encoding="utf-8")))
            for f in sorted((root / "tests" / "fixtures" / "dryrun").glob("*.json"))]


def load_research_file(path: Path) -> tuple[str | None, list[tuple[ResearchResult, dict[str, Any]]]]:
    """Research JSON from a Claude session: {"mode": ..., "jobs": [{label, product_ids, urls,
    page_ages, searches, offers, dead_codes}]} (see docs/RESEARCH_PROTOCOL.md)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = {"jobs": data}
    return data.get("mode"), [_job_from_dict(j) for j in data.get("jobs", [])]


def research_plan(cfg: Config, state: State, mode: str, slot: str, note: str, only: str | None,
                  d: date) -> dict[str, Any]:
    budgets = {"quick": 10, "deep": 4, "calibrate": 5}
    jobs = [] if mode in ("skip", "check", "init") else [
        {"label": label, "product_ids": pids, "search_budget": budgets.get(mode, 8) if len(pids) == 1 else
         (6 if slot == "midday" else budgets["quick"]), "task": prompt}
        for label, pids, prompt, _ in build_jobs(cfg, mode, slot, only, d)]
    return {
        "date": d.isoformat(), "slot": slot, "mode": mode, "note": note,
        "case_min_units": int(cfg.settings["research"].get("case_min_units", 12)),
        "jobs": jobs,
        "dead_codes": state.memory.get("dead_codes", []),
        "records": {pid: pm.get("all_time_low") for pid, pm in state.memory["products"].items()
                    if pid in cfg.products and cfg.products[pid].enabled},
        "rules": "Follow docs/RESEARCH_PROTOCOL.md exactly. Write the JSON to a file and run "
                 "`python deal_hunter.py --ingest <file>`.",
    }


def _price_all(offers: list[dict[str, Any]], cfg: Config) -> list[dict[str, Any]]:
    priced = []
    for o in offers:
        p = cfg.products.get(o["product_id"])
        if not p or not p.enabled:
            continue
        o = {k: v for k, v in o.items() if k not in ("is_record", "previous_record")}
        o.update(price_offer(o, p, p.ref_unit_price, cfg.settings))
        o["category"] = p.category
        priced.append(o)
    return priced


def _slim(o: dict[str, Any], with_playbook: bool) -> dict[str, Any]:
    s = {k: o.get(k) for k in SLIM_KEYS}
    s["evidence_text"] = (o.get("evidence_text") or "")[:140]
    if with_playbook:
        s["playbook"] = o.get("playbook", [])
    return s


def build_latest(cfg: Config, state: State, ranked: list[dict[str, Any]], heroes: dict[str, Any],
                 run_meta: dict[str, Any]) -> dict[str, Any]:
    per = int(cfg.settings["research"]["offers_per_product_in_app"])
    products = []
    for p in cfg.enabled():
        pm = state.memory["products"].get(p.id, {})
        offers = [o for o in ranked if o["product_id"] == p.id]
        verified = [o for o in offers if not o.get("unverified")]
        best = verified[0] if verified else (offers[0] if offers else None)
        products.append({
            "id": p.id, "category": p.category, "display_name": p.display_name, "brand": p.brand,
            "unit_label": p.unit_label, "unit_size_oz": p.unit_size_oz, "protein_g": p.protein_g,
            "ref_unit_price": p.ref_unit_price, "ref_source": pm.get("ref_source", "seed"),
            "plant_based": p.plant_based, "all_time_low": pm.get("all_time_low"),
            "trend_30d": pm.get("trend_30d", "flat"),
            "best": _slim(best, True) if best else None,
            "offers": [_slim(o, o is best) for o in offers[:per]],
        })
    board = sorted(
        ({"product_id": p["id"], "display_name": p["display_name"], "category": p["category"],
          "price_per_10g_protein": p["best"]["price_per_10g_protein"], "unit_price": p["best"]["unit_price"],
          "retailer_name": p["best"]["retailer_name"], "tier": p["best"]["tier"],
          "protein_value_badge": p["best"]["protein_value_badge"], "source_url": p["best"]["source_url"]}
         for p in products if p["category"] != "energy" and p["best"] and not p["best"].get("unverified")
         and p["best"].get("price_per_10g_protein") is not None),
        key=lambda r: r["price_per_10g_protein"])
    vis = [o for o in ranked if not o.get("unverified")]
    return {
        "schema": 1, "version": __version__, "generated_at": iso_now(), **run_meta, "stale": False,
        "app_url": cfg.settings["app_url"],
        "heroes": {k: _slim(v, True) if v else None for k, v in heroes.items()},
        "products": products,
        "protein_value_board": board,
        "counts": {"offers": len(ranked), "hot_plus": sum(is_hot_plus(o["tier"]) for o in vis),
                   "steals": sum(o["tier"] == STEAL for o in vis),
                   "records": sum(bool(o.get("is_record")) for o in vis),
                   "unverified": sum(bool(o.get("unverified")) for o in ranked),
                   "products_with_offers": sum(1 for p in products if p["offers"])},
    }


def _write_status(data_dir: Path, payload: dict[str, Any]) -> None:
    write_json(data_dir / "status.json", payload)


def _gh_output(**kv: Any) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for k, v in kv.items():
            fh.write(f"{k}={v}\n")


# ------------------------------------------------------------------ main run
def run(opts: RunOptions) -> RunResult:
    if opts.dry_run and not os.environ.get("DEAL_RADAR_NOW"):
        os.environ["DEAL_RADAR_NOW"] = "2026-11-16T07:17:00-08:00"
    cfg = load_config(opts.root)
    out_root = opts.out or (opts.root / ".dryrun" if opts.dry_run else opts.root)
    data_dir = out_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    state = State.load(data_dir, cfg)
    state.apply_overrides(cfg)
    d = today_fn()
    slot = detect_slot(cfg, opts.slot)
    mode, note = resolve_mode(cfg, state, opts.mode, slot, d)
    if opts.only and mode == "quick":
        mode = "deep"  # --only implies a single-product research call
    ingest_jobs: list[tuple[ResearchResult, dict[str, Any]]] | None = None
    if opts.ingest:
        file_mode, ingest_jobs = load_research_file(opts.ingest)
        if opts.mode == "auto" and file_mode:
            mode = file_mode
    if opts.plan:
        print(json.dumps(research_plan(cfg, state, mode, slot, note, opts.only, d), ensure_ascii=False, indent=1))
        return RunResult(mode=mode, slot=slot, status="plan", reason=note)
    tracker = CostTracker(prices=cfg.settings["prices"], max_run_usd=float(cfg.settings["budget"]["max_run_usd"]))
    res = RunResult(mode=mode, slot=slot, status="ok", reason=note)
    app_url = cfg.settings["app_url"]
    base_status = {"version": __version__, "last_run_at": iso_now(), "date": d.isoformat(),
                   "slot": slot, "dry_run": opts.dry_run}

    def finish(status: str, reason: str, *, push_failure: bool) -> RunResult:
        res.status, res.reason = status, reason
        if push_failure:
            payloads = plan_pushes(state, cfg, records=[], ranked=[], heroes={}, send_digest=False,
                                   failure=reason, app_url=app_url)
            res.pushes = send(payloads, cfg, dry=opts.dry_run or opts.no_push)
        if state.latest and status == "failed":
            state.latest["stale"] = True
            state.latest["stale_reason"] = reason
        if tracker.calls or opts.ingest:
            record_run(state.memory, d, tracker)
        state.memory["latest_run"] = {"date": d.isoformat(), "mode": mode, "status": status,
                                      "cost_usd": round(tracker.usd, 4), "searches": tracker.searches}
        state.save(write_latest=bool(state.latest))
        _write_status(data_dir, {**base_status, "mode": mode, "status": status, "reason": reason,
                                 "cost_usd": round(tracker.usd, 4), "searches": tracker.searches,
                                 "month_usd": round(month_spend(state.memory, d), 4),
                                 "budget_cap_usd": cfg.monthly_budget, "heartbeat": iso_now()})
        _gh_output(status=status, mode=mode, commit="false" if opts.no_commit else "true")
        res.exit_code = 1 if status == "failed" else 0
        res.cost_usd, res.searches = tracker.usd, tracker.searches
        return res

    if mode == "skip":
        return finish("skipped", note, push_failure=False)
    if mode == "init":  # empty-state outputs for a fresh deploy; no API calls
        state.latest = build_latest(cfg, state, [], {"energy": None, "snack": None, "rtd": None},
                                    {"date": d.isoformat(), "run_mode": "init", "slot": slot, "status": "awaiting first scan"})
        state.latest["generated_at"] = None
        write_vault(out_root, cfg, state, {"date": d, "mode": "init", "status": "awaiting first scan", "cost_usd": 0.0,
                                           "ranked": [], "heroes": {}, "records": [], "dropped": [], "corrections": [],
                                           "best_by_product": {}, "note": "Empty state before the first scan."})
        return finish("ok", "initialized empty state", push_failure=False)

    # budget
    cap = cfg.monthly_budget
    bstate = budget_state(state.memory, d, cap, float(cfg.settings["budget"]["downgrade_at_pct"]))
    if bstate == "exhausted" and not opts.dry_run and not opts.ingest:
        warn = state.memory.get("budget_warning_month") != month_key(d)
        state.memory["budget_warning_month"] = month_key(d)
        return finish("skipped", f"monthly budget ${cap:.2f} reached (${month_spend(state.memory, d):.2f} spent); "
                      "research paused, app keeps last data", push_failure=warn)
    if bstate == "downgrade" and mode == "deep":
        mode = res.mode = "quick"
        note = (note + "; " if note else "") + "budget above 80%: deep downgraded to quick"

    if not opts.dry_run and not opts.ingest and not cfg.api_key:
        return finish("failed", "ANTHROPIC_API_KEY is not set (add it under repo Settings → Secrets → Actions)",
                      push_failure=True)

    # ---------------- research + extraction
    jobs_out: list[tuple[ResearchResult, dict[str, Any]]] = []
    errors: list[str] = []
    if ingest_jobs is not None:
        jobs_out = ingest_jobs
        tracker.searches = sum(r.searches for r, _ in jobs_out)
        if not jobs_out:
            return finish("failed", f"research file {opts.ingest} has no jobs", push_failure=True)
    elif opts.dry_run:
        jobs_out = _fixture_jobs(opts.root)
        if opts.only:
            jobs_out = [(r, x) for r, x in jobs_out if opts.only in r.product_ids]
    else:
        client = _anthropic_client(cfg)
        system = build_system(cfg, state.memory)
        model = cfg.settings["models"]["research"].get(mode, cfg.settings["models"]["research"]["quick"])
        researcher = Researcher(cfg, client, tracker, model)
        from .extract import extract
        for label, pids, user, max_uses in build_jobs(cfg, mode, slot, opts.only, d):
            try:
                r = researcher.run(label, pids, system, user, max_uses)
                if mode == "check":
                    jobs_out.append((r, {"offers": [], "dead_codes": []}))
                    continue
                data = extract(cfg, client, tracker, r.dossier, list(r.urls.values()), pids, d.isoformat())
                jobs_out.append((r, data))
                log.info("%s: %d urls, %d searches, %d offers", label, len(r.urls), r.searches, len(data["offers"]))
            except WebSearchDisabled as e:
                return finish("failed", "Web search is not enabled for this API org. Turn it on at "
                              "platform.claude.com/settings/privacy (Capabilities). " + str(e)[:200],
                              push_failure=True)
            except BudgetExceeded as e:
                errors.append(f"{label}: {e}")
                break
            except Exception as e:  # noqa: BLE001 — one product failing never kills the run
                log.exception("job %s failed", label)
                errors.append(f"{label}: {type(e).__name__}: {str(e)[:160]}")

    if mode == "check":
        urls = sum(len(r.urls) for r, _ in jobs_out)
        if errors or not jobs_out:
            return finish("failed", "API check failed: " + "; ".join(errors), push_failure=True)
        res.pushes = send([{"title": "✅ Deal Radar connected", "priority": 3, "tags": ["white_check_mark"],
                            "message": f"API key + web search OK ({urls} result URLs, "
                                       f"${tracker.usd:.4f}). Push alerts work.", "click": app_url}],
                          cfg, dry=opts.dry_run or opts.no_push)
        return finish("ok", f"API check passed: web search returned {urls} URLs", push_failure=False)

    # ---------------- validation + pricing
    kept_all, dropped_all, dead_reports = [], [], []
    for r, data in jobs_out:
        kept, dropped = validate_offers(data.get("offers", []), cfg, r.urls, r.page_ages,
                                        state.memory["dead_codes"], d)
        kept_all += kept
        dropped_all += dropped
        dead_reports += dead_codes_from_reports(data.get("dead_codes", []), r.urls, cfg, d)
    add_dead_codes(state, dead_reports)
    prune_codes(state, d)

    corrections: list[dict[str, Any]] = []
    if mode == "calibrate":
        corrections = calibrate(state, cfg, kept_all, d)
        state.apply_overrides(cfg)
    res.corrections = corrections

    merge_offers(state, _price_all(kept_all, cfg), cfg, d)
    current = _price_all(current_offers(state, cfg, d), cfg)  # re-price with today's refs
    flag_unverified(current, cfg)
    ranked = sorted(current, key=rank_key)
    best_by_product: dict[str, dict[str, Any]] = {}
    for o in ranked:
        if not o.get("unverified"):
            best_by_product.setdefault(o["product_id"], o)
    records = detect_records(state, best_by_product, d)
    update_history(state, best_by_product, d)
    record_active_codes(state, [o for o in kept_all], d)
    heroes = {cat: next((o for o in ranked if o["category"] == cat and not o.get("unverified")), None)
              for cat in ("energy", "snack", "rtd")}

    # failed = every research job errored; partial = some did; ok = none did
    status = "failed" if not jobs_out else ("partial" if errors else "ok")
    reason = "; ".join(filter(None, [note, *errors]))[:600]

    run_meta = {"date": d.isoformat(), "run_mode": mode, "slot": slot, "status": status}
    if status != "failed":
        state.latest = build_latest(cfg, state, ranked, heroes, run_meta)
    res.products_with_offers = len({o["product_id"] for o in ranked})

    write_vault(out_root, cfg, state, {
        "date": d, "mode": mode, "status": status, "cost_usd": tracker.usd, "ranked": ranked,
        "heroes": heroes, "records": records, "dropped": dropped_all, "corrections": corrections,
        "best_by_product": best_by_product, "note": reason})

    send_digest = slot in ("morning", "manual") or mode == "calibrate"
    payloads = plan_pushes(state, cfg, records=records, ranked=ranked, heroes=heroes,
                           send_digest=send_digest and status != "failed",
                           failure=(f"Run failed: {reason}" if status == "failed" else None), app_url=app_url)
    res.pushes = send(payloads, cfg, dry=opts.dry_run or opts.no_push)
    return finish(status, reason, push_failure=False)


def main_from_cli(opts: RunOptions) -> int:
    logging.basicConfig(level=logging.WARNING if opts.plan else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr if opts.plan else sys.stdout)
    r = run(opts)
    if opts.plan:
        return 0
    print(f"radar: mode={r.mode} slot={r.slot} status={r.status} cost=${r.cost_usd:.4f} "
          f"searches={r.searches} products_with_offers={r.products_with_offers}")
    if r.reason:
        print(f"radar: note: {r.reason}")
    for c in r.corrections:
        print(f"radar: correction {c['product_id']}.{c['field']}: {c['old']} -> {c['new']} ({c['basis']})")
    for p in r.pushes:
        print(f"radar: push {p}")
    return r.exit_code
