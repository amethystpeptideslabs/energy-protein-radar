"""Markdown writers for the Obsidian vault mirror (Obsidian-Vault/ -> <VAULT>/Deal-Radar/)."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from .config import CATEGORY_LABEL, Config
from .memory import State
from .pricing import is_unavailable, rank_key
from .tiers import RECORD_BADGE, TIER_EMOJI, UNVERIFIED_BADGE, tier_label
from .util import write_text

BANNER = "> [!info] Auto-generated — personal notes go outside Deal-Radar/\n"
CAT_ICON = {"energy": "⚡", "snack": "🍫", "rtd": "🥤"}
TREND = {"down": "↘️", "flat": "→", "up": "↗️"}
PROMO_LABEL = {"bogo_50": "🎁 BOGO 50% (add 2)", "bogo_free": "🎁 BOGO free (add 2)", "pct_off": "🏷️ Sale",
               "fixed_unit_price": "🏷️ Promo price", "multi_buy": "🏷️ Multi-buy"}


def _cell(v: Any) -> str:
    s = "" if v is None else str(v)
    return s.replace("|", "\\|").replace("\n", " ")


def _yaml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _money(v: Any) -> str:
    return "" if v is None else f"${float(v):.2f}"


def _unit(cfg: Config, pid: str) -> str:
    return cfg.products[pid].unit_label.split(" ")[0]


def _offer_summary(o: dict[str, Any] | None, cfg: Config) -> str:
    if not o:
        return "none"
    return (f"{cfg.products[o['product_id']].display_name} {_money(o['unit_price'])}/"
            f"{_unit(cfg, o['product_id'])} @ {o.get('retailer_name', '')}")


def _badges(o: dict[str, Any]) -> str:
    b = tier_label(o["tier"])
    if o.get("is_record"):
        b += f" {RECORD_BADGE}"
    if o.get("unverified"):
        b += f" {UNVERIFIED_BADGE} UNVERIFIED"
    return b


def _table(rows: list[dict[str, Any]], cfg: Config, cat: str) -> str:
    metric = "$/oz" if cat == "energy" else "$/10g protein"
    head = (f"| Product | Retailer | Pack | Final $ | $/unit | {metric} | vs ref | Tier | Code | Ends | Link |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|\n")
    if not rows:
        return head + "| _no sourced offers this run_ | | | | | | | | | | |\n"
    out = []
    for o in rows:
        m = o.get("price_per_oz") if cat == "energy" else o.get("price_per_10g_protein")
        vs = "" if o.get("pct_vs_ref") is None else f"{o['pct_vs_ref']:.0f}%"
        pack = f"{o['packs_in_cart']}× {o.get('pack_count', 1)}"
        out.append("| " + " | ".join(_cell(x) for x in (
            cfg.products[o["product_id"]].display_name, o.get("retailer_name", ""), pack,
            _money(o["effective_pack_total"]), _money(o["unit_price"]), _money(m), vs, _badges(o),
            o.get("code") or "", o.get("ends") or "", f"[Open deal]({o['source_url']})")) + " |")
    return head + "\n".join(out) + "\n"


def write_vault(root: Path, cfg: Config, state: State, run: dict[str, Any]) -> list[Path]:
    """run keys: date, mode, status, cost_usd, ranked, heroes, records, dropped, corrections."""
    vault = root / "Obsidian-Vault"
    written = [write_log(vault, cfg, run), write_master(vault, cfg, state, run), write_drive_note(vault, cfg, run)]
    for pid in cfg.products:
        if cfg.products[pid].enabled:
            written.append(write_product(vault, cfg, state, pid, run))
    written.append(write_dead_codes(vault, state))
    written.append(write_playbooks(vault, cfg))
    return written


def write_drive_note(vault: Path, cfg: Config, run: dict[str, Any]) -> Path:
    """Compact, self-contained note for the separate 'Deal Radar' vault in Google Drive.
    Append-only: each run uploads this as '<date> <HHMM> <mode>.md' (Drive can't overwrite)."""
    d: date = run["date"]
    ranked = [o for o in run["ranked"] if not o.get("unverified")]
    deals = [o for o in ranked if o["tier"] in ("STEAL", "HOT", "SOLID")]
    seen: set[str] = set()
    best_deals = []
    for o in deals:  # best deal per product
        if o["product_id"] not in seen:
            seen.add(o["product_id"])
            best_deals.append(o)
    lines = ["---", f"date: {d.isoformat()}", f"run_mode: {run['mode']}", f"status: {run['status']}",
             f"deals: {len(best_deals)}", "tags: [deal-radar]", "---", "",
             f"# Deals {d.strftime('%a %b %d, %Y')}", "",
             f"📱 [Open the Deal Radar app]({cfg.settings['app_url']})", ""]
    lines += ["## 🔥 Deals today (tap Open deal)", ""]
    if best_deals:
        lines += ["| Deal | Per unit | You pay | Store | Where | Tier | Link |", "|---|---|---|---|---|---|---|"]
        for o in best_deals:
            lines.append(_deal_row(cfg, o, tier_label(o["tier"]) + (f" {RECORD_BADGE}" if o.get("is_record") else "")))
    else:
        lines.append("No HOT/STEAL/SOLID deals this run.")
    lines.append("")
    amazon = [o for o in ranked if o.get("retailer_key") == "amazon" and o["tier"] in ("STEAL", "HOT", "SOLID")]
    if amazon:  # Amazon gets its own list so its deals are easy to find (all flavors, not just the best one)
        lines += ["## 🛒 Amazon deals", "",
                  "| Deal | Per unit | You pay | Store | Where | Tier | Link |", "|---|---|---|---|---|---|---|"]
        for o in amazon:
            posted = f" · posted {o['evidence_date']}" if o.get("evidence_date") else ""
            lines.append(_deal_row(cfg, o, tier_label(o["tier"]) + posted))
        lines.append("")
    shown = {id(o) for o in best_deals}
    promos = sorted((o for o in ranked if o.get("promo_type") in PROMO_LABEL and id(o) not in shown), key=rank_key)
    if promos:  # every live BOGO / sale, same as the app's section; in stock near you first
        lines += ["## 🎁 BOGO & sales right now", "",
                  "| Deal | Per unit | You pay | Store | Where | Promo | Link |", "|---|---|---|---|---|---|---|"]
        lines += [_deal_row(cfg, o, PROMO_LABEL[o["promo_type"]]) for o in promos]
        lines.append("")
    lines += all_products_table(cfg, run)
    lines += ["## 🧾 How to get the top price", ""]
    for cat in ("energy", "snack", "rtd"):
        h = run["heroes"].get(cat)
        if h:
            lines.append(f"**{CAT_ICON[cat]} {cfg.products[h['product_id']].display_name} @ {h.get('retailer_name')}**")
            lines += [f"{i}. {s}" for i, s in enumerate(h.get("playbook", []), 1)]
            lines += [f"[Open deal]({h['source_url']})", ""]
    path = vault / "Drive-Upload" / "latest.md"
    write_text(path, "\n".join(lines) + "\n")
    return path


def write_log(vault: Path, cfg: Config, run: dict[str, Any]) -> Path:
    d: date = run["date"]
    ranked = run["ranked"]
    heroes = run["heroes"]
    records = run["records"]
    snack, rtd = heroes.get("snack"), heroes.get("rtd")
    energy = heroes.get("energy")
    protein = [o for o in ranked if o["category"] != "energy" and o.get("price_per_10g_protein")
               and not o.get("unverified")]
    best_p10 = min((o["price_per_10g_protein"] for o in protein), default=None)
    fm = ["---", f"date: {d.isoformat()}", "tags: [deal-radar, energy, protein]",
          f"run_mode: {run['mode']}", f"status: {run['status']}",
          f"best_energy: {_yaml_str(_offer_summary(energy, cfg))}",
          f"lowest_ppc: {energy['unit_price'] if energy else 'null'}",
          f"best_snack: {_yaml_str(_offer_summary(snack, cfg))}",
          f"best_rtd: {_yaml_str(_offer_summary(rtd, cfg))}",
          f"best_protein_per_10g: {best_p10 if best_p10 is not None else 'null'}",
          f"new_records: {len(records)}", f"cost_usd: {run['cost_usd']:.4f}", "---", ""]
    body = [BANNER, f"# Deal Run — {d.strftime('%A %Y-%m-%d')} ({run['mode']}, {run['status']})", "",
            f"📱 [Open the Deal Radar app]({cfg.settings['app_url']})", ""]
    if run.get("note"):
        body += [f"> [!note] {run['note']}", ""]
    if records:
        body.append(f"> [!danger] {RECORD_BADGE} New all-time lows")
        for o in records:
            prev = (o.get("previous_record") or {}).get("unit_price")
            body.append(f"> - **{cfg.products[o['product_id']].display_name}** {_money(o['unit_price'])}/"
                        f"{_unit(cfg, o['product_id'])} at {o.get('retailer_name')} (was {_money(prev)}) "
                        f"[link]({o['source_url']})")
        body.append("")
    top = [o for o in ranked if not o.get("unverified")][:3]
    body.append("> [!tip] Today's top 3")
    if top:
        for i, o in enumerate(top, 1):
            body.append(f"> {i}. {_offer_summary(o, cfg)} — {_badges(o)}")
    else:
        body.append("> No sourced offers yet.")
    body.append("")
    restricted = [o for o in ranked if o.get("in_store_only") or o.get("membership_required")
                  or int(o.get("limit_per_customer") or 0) or int(o.get("min_qty") or 1) > 1]
    if restricted:
        body.append("> [!warning] In-store only / limits / memberships")
        for o in restricted[:15]:
            bits = []
            if o.get("in_store_only"):
                bits.append("🏬 in-store only")
            if o.get("membership_required"):
                bits.append("🔒 membership")
            if int(o.get("limit_per_customer") or 0):
                bits.append(f"limit {o['limit_per_customer']}")
            if int(o.get("min_qty") or 1) > 1:
                bits.append(f"min {o['min_qty']}")
            body.append(f"> - {_offer_summary(o, cfg)}: {', '.join(bits)}")
        body.append("")
    for cat in ("energy", "snack", "rtd"):
        rows = [o for o in ranked if o["category"] == cat]
        body += [f"## {CAT_ICON[cat]} {CATEGORY_LABEL[cat]}", "", _table(rows, cfg, cat)]
    body += all_products_table(cfg, run)
    body += ["## 🧾 Cart Stacking Playbook", ""]
    for cat in ("energy", "snack", "rtd"):
        h = heroes.get(cat)
        if not h:
            continue
        body.append(f"### {CAT_ICON[cat]} {cfg.products[h['product_id']].display_name} @ {h.get('retailer_name')}")
        body += [f"{i}. {s}" for i, s in enumerate(h.get("playbook", []), 1)]
        body.append(f"\n[Open deal]({h['source_url']})\n")
    if run.get("corrections"):
        body += ["## 🔧 Calibration corrections", "", "| Product | Field | Seed | Verified | Basis |",
                 "|---|---|---|---|---|"]
        for c in run["corrections"]:
            body.append(f"| {c['product_id']} | {c['field']} | {c['old']} | {c['new']} | {_cell(c['basis'])} |")
        body.append("")
    dropped = run.get("dropped", [])
    if dropped:
        body.append(f"> [!failure]- Dropped offers ({len(dropped)}: unsourced/stale/wrong product)")
        for o in dropped[:60]:
            body.append(f"> - `{o.get('drop_reason')}` {o.get('product_id', '?')} @ {o.get('retailer', '?')}"
                        f" — {_cell(o.get('drop_detail', ''))}")
        body.append("")
    path = vault / "Logs" / f"{d.isoformat()}-Deal-Run.md"
    write_text(path, "\n".join(fm + body) + "\n")
    return path


def all_products_table(cfg: Config, run: dict[str, Any]) -> list[str]:
    """Every tracked product in one table so each dated log stands alone (append-only vaults)."""
    best = run.get("best_by_product", {})
    state = run.get("state")
    lines = ["## 📋 All products today", "",
             "| Product | Best now | Pack | Store | Tier | Usual | All-time low | Link |",
             "|---|---|---|---|---|---|---|---|"]
    for cat in ("energy", "snack", "rtd"):
        for p in cfg.enabled(cat):
            b = best.get(p.id)
            atl = ((state.memory["products"].get(p.id, {}) if state else {}).get("all_time_low") or {})
            unit = p.unit_label.split(" ")[0]
            if b:
                pack = f"{_money(b['effective_pack_total'])} for {b['units_in_cart']}" + (" 📦" if b.get("is_case") else "")
                row = (f"{CAT_ICON[cat]} {p.display_name}", f"{_money(b['unit_price'])}/{unit}", pack,
                       b.get("retailer_name", ""), tier_label(b["tier"]), _money(p.ref_unit_price),
                       _money(atl.get("unit_price")), f"[Open deal]({b['source_url']})")
            else:
                row = (f"{CAT_ICON[cat]} {p.display_name}", "no offer found", "", "", "", _money(p.ref_unit_price),
                       _money(atl.get("unit_price")), "")
            lines.append("| " + " | ".join(_cell(x) for x in row) + " |")
    return lines + [""]


def write_master(vault: Path, cfg: Config, state: State, run: dict[str, Any]) -> Path:
    best = run.get("best_by_product", {})
    lines = [BANNER, "# 00 · Master Deal Profile", "",
             f"_Updated {run['date'].isoformat()} after the {run['mode']} run._", ""]
    for cat in ("energy", "snack", "rtd"):
        lines += [f"## {CAT_ICON[cat]} {CATEGORY_LABEL[cat]}", "",
                  "| Product | Ref $/unit | All-time low | Record at | Record date | Today's best | Best retailer now | 30d |",
                  "|---|---|---|---|---|---|---|---|"]
        for p in cfg.enabled(cat):
            pm = state.memory["products"].get(p.id, {})
            atl = pm.get("all_time_low") or {}
            b = best.get(p.id)
            lines.append("| " + " | ".join(_cell(x) for x in (
                f"[[{p.id}|{p.display_name}]]", _money(p.ref_unit_price), _money(atl.get("unit_price")),
                atl.get("retailer", ""), atl.get("date", ""),
                (f"{_money(b['unit_price'])} {TIER_EMOJI[b['tier']]}" if b else "—"),
                (b.get("retailer_name", "") if b else ""), TREND.get(pm.get("trend_30d", "flat"), "→"))) + " |")
        lines.append("")
    path = vault / "00-Master-Deal-Profile.md"
    write_text(path, "\n".join(lines) + "\n")
    return path


def write_product(vault: Path, cfg: Config, state: State, pid: str, run: dict[str, Any]) -> Path:
    p = cfg.products[pid]
    pm = state.memory["products"].get(pid, {})
    atl = pm.get("all_time_low") or {}
    fm = ["---", f"product_id: {pid}", f"category: {p.category}", f"display_name: {_yaml_str(p.display_name)}",
          f"ref_unit_price: {p.ref_unit_price if p.ref_unit_price is not None else 'null'}",
          f"ref_source: {_yaml_str(pm.get('ref_source', 'seed'))}",
          f"all_time_low: {atl.get('unit_price', 'null')}",
          f"all_time_low_retailer: {_yaml_str(atl.get('retailer', ''))}",
          f"protein_g: {p.protein_g:g}", f"unit_size_oz: {p.unit_size_oz:g}",
          "tags: [deal-radar, product]", "---", ""]
    body = [BANNER, f"# {p.display_name}", "",
            f"Unit: {p.unit_label} · Size: {p.unit_size_oz:g} oz" + (f" · Protein: {p.protein_g:g}g" if p.protein_g else ""),
            ""]
    cur = [o for o in run["ranked"] if o["product_id"] == pid]
    if cur:
        body += ["## Current offers", "", _table(cur, cfg, p.category)]
    body += ["## Price ledger", "", "| Date | Best $/unit | Tier | Retailer |", "|---|---|---|---|"]
    for row in reversed(state.history.get(pid, [])[-120:]):
        body.append(f"| {row[0]} | {_money(row[1])} | {tier_label(row[2]) if row[2] in TIER_EMOJI else row[2]} | "
                    f"{_cell(row[3] if len(row) > 3 else '')} |")
    path = vault / "Products" / f"{pid}.md"
    write_text(path, "\n".join(fm + body) + "\n")
    return path


def write_dead_codes(vault: Path, state: State) -> Path:
    lines = [BANNER, "# Dead codes", "", "Codes reported expired/invalid are skipped until `skip_until`.", "",
             "| Code | Retailer | Reason | First seen dead | Skip until |", "|---|---|---|---|---|"]
    for d in state.memory.get("dead_codes", []):
        lines.append(f"| `{_cell(d['code'])}` | {_cell(d.get('retailer'))} | {d.get('reason')} | "
                     f"{d.get('first_seen_dead')} | {d.get('skip_until')} |")
    lines += ["", "## Active codes (reported, not tested)", "", "| Code | Retailer | Reported on | Expires | Source |",
              "|---|---|---|---|---|"]
    for c in state.memory.get("active_codes", [])[-50:]:
        lines.append(f"| `{_cell(c['code'])}` | {_cell(c.get('retailer'))} | {c.get('reported_on')} | "
                     f"{c.get('expires') or ''} | [source]({c.get('source_url')}) |")
    path = vault / "Reference" / "Dead-Codes.md"
    write_text(path, "\n".join(lines) + "\n")
    return path


def write_playbooks(vault: Path, cfg: Config) -> Path:
    lines = [BANNER, "# Retailer stacking playbooks", ""]
    for key, r in cfg.settings.get("retailers", {}).items():
        lock = " 🔒" if r.get("membership") else ""
        lines += [f"## {r['name']}{lock}", f"- Domains: {', '.join(r['domains'])}",
                  f"- {r.get('playbook', '')}", ""]
    path = vault / "Reference" / "Retailer-Playbooks.md"
    write_text(path, "\n".join(lines) + "\n")
    return path


def _deal_row(cfg: Config, o: dict[str, Any], label: str) -> str:
    p = cfg.products[o["product_id"]]
    unit = p.unit_label.split(" ")[0]
    where = {"in_store": "🏬 In store (local)", "pickup": "📍 Local pickup",
             "ship": "🚚 Ships to you"}.get(o.get("fulfillment", ""), "Online")
    if o.get("local_store"):
        where += f" at {o['local_store']}"
    if o.get("membership_required"):
        where += " 🔒"
    if o.get("stock_note"):
        where += f" {'⚠️' if is_unavailable(o) else '✅'} {o['stock_note']}"
    pay = f"{_money(o['effective_pack_total'])} for {o['units_in_cart']}" + (" 📦 case" if o.get("is_case") else "")
    name = f"{CAT_ICON[o['category']]} {p.display_name}" + (f" ({o['flavor']})" if o.get("flavor") else "")
    return "| " + " | ".join(_cell(x) for x in (
        name, f"{_money(o['unit_price'])}/{unit}", pay, o.get("retailer_name", ""), where, label,
        f"[Open deal]({o['source_url']})")) + " |"
