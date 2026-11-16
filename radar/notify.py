"""ntfy push alerts, published as JSON (POST to the server root) so emoji titles never
touch HTTP headers. Max 3 pushes per run; extras roll into the digest. UNVERIFIED offers
are never pushed. The topic is read from the environment and never written to disk."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from .config import Config
from .memory import State, alert_recently_sent, remember_alert
from .tiers import RECORD_BADGE, STEAL, TIER_EMOJI, is_hot_plus

log = logging.getLogger("radar.notify")


def fingerprint(o: dict[str, Any]) -> str:
    return f"{o['product_id']}|{o.get('retailer_key')}|{o['unit_price']:.2f}|{(o.get('code') or '').upper()}"


def _price_line(o: dict[str, Any], cfg: Config) -> str:
    p = cfg.products[o["product_id"]]
    unit = p.unit_label.split(" ")[0]
    s = f"${o['unit_price']:.2f}/{unit}"
    if o.get("price_per_10g_protein") is not None and not p.is_energy:
        s += f" · ${o['price_per_10g_protein']:.2f}/10g"
    if o.get("pct_vs_ref") is not None and not p.is_energy:
        s += f" · {100 - o['pct_vs_ref']:.0f}% under ref"
    return s


def _pack(o: dict[str, Any], cfg: Config) -> str:
    if o.get("effective_pack_total") is None:
        return ""
    unit = cfg.products[o["product_id"]].unit_label.split(" ")[0]
    n = int(o.get("units_in_cart") or 1)
    how = {"in_store": ", in store", "pickup": ", local pickup", "ship": ", ships"}.get(o.get("fulfillment", ""), "")
    return f"${o['effective_pack_total']:.2f} for {n} {unit}{'s' if n > 1 else ''}" + (" (case)" if o.get("is_case") else "") + how


def _restrictions(o: dict[str, Any]) -> str:
    bits = []
    if o.get("in_store_only"):
        bits.append("🏬 in-store")
    if o.get("membership_required"):
        bits.append("🔒 membership")
    if int(o.get("limit_per_customer") or 0):
        bits.append(f"limit {o['limit_per_customer']}")
    if o.get("code"):
        bits.append(f"code {o['code']}")
    if o.get("ends"):
        bits.append(f"ends {o['ends']}")
    return " · ".join(bits)


def plan_pushes(state: State, cfg: Config, *, records: list[dict[str, Any]],
                ranked: list[dict[str, Any]], heroes: dict[str, Any], send_digest: bool,
                failure: str | None, app_url: str) -> list[dict[str, Any]]:
    ncfg = cfg.settings["notify"]
    cap = int(ncfg["max_pushes_per_run"])
    payloads: list[dict[str, Any]] = []
    if failure:
        payloads.append({"title": "⚠️ Deal Radar run problem", "priority": 3, "tags": ["warning"],
                         "message": failure, "click": app_url})
        return payloads

    singles: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for o in records:
        if o.get("unverified"):
            continue
        prev = o.get("previous_record") or {}
        msg = (f"**{cfg.products[o['product_id']].display_name}** at {o.get('retailer_name')}\n"
               f"{_price_line(o, cfg)} (was record ${float(prev.get('unit_price', 0)):.2f})\n{_pack(o, cfg)}\n"
               f"{_restrictions(o)}")
        singles.append((5, o, {
            "title": f"{RECORD_BADGE} New all-time low: {cfg.products[o['product_id']].display_name}",
            "message": msg.strip(), "priority": 5, "tags": ["trophy"], "click": o["source_url"],
            "actions": [{"action": "view", "label": f"Open at {o.get('retailer_name') or 'store'}", "url": o["source_url"]},
                        {"action": "view", "label": "Open app", "url": app_url}]}))
    record_ids = {id(o) for o in records}
    for o in ranked:
        if o.get("unverified") or o.get("tier") != STEAL or id(o) in record_ids:
            continue
        if alert_recently_sent(state, fingerprint(o), int(ncfg["steal_dedupe_hours"])):
            continue
        singles.append((4, o, {
            "title": f"{TIER_EMOJI[STEAL]} STEAL: {cfg.products[o['product_id']].display_name}",
            "message": (f"{o.get('retailer_name')}: {_price_line(o, cfg)}\n{_pack(o, cfg)}\n{_restrictions(o)}").strip(),
            "priority": 4, "tags": ["rotating_light"], "click": o["source_url"],
            "actions": [{"action": "view", "label": "Open deal", "url": o["source_url"]},
                        {"action": "view", "label": "Open app", "url": app_url}]}))

    leftovers = [o for (_, o, _) in singles]
    budget_for_singles = cap - 1 if (send_digest or len(singles) > cap) else cap
    for prio, o, payload in singles[:max(0, budget_for_singles)]:
        payloads.append(payload)
        remember_alert(state, fingerprint(o), prio)
        leftovers.remove(o)

    if send_digest or leftovers:
        lines = []
        for cat, label in (("energy", "⚡ Energy"), ("snack", "🍫 Snack"), ("rtd", "🥤 RTD")):
            h = heroes.get(cat)
            if h:
                lines.append(f"{label}: [{cfg.products[h['product_id']].display_name}]({h['source_url']}) "
                             f"{_price_line(h, cfg)} @ {h.get('retailer_name')} ({_pack(h, cfg)}) "
                             f"{TIER_EMOJI.get(h['tier'], '')}")
            else:
                lines.append(f"{label}: no sourced offers today")
        hot = sum(1 for o in ranked if is_hot_plus(o.get("tier", "")) and not o.get("unverified"))
        lines.append(f"HOT+ deals: {hot}")
        if leftovers:
            lines.append("Also: " + "; ".join(
                f"{cfg.products[o['product_id']].display_name} ${o['unit_price']:.2f}" for o in leftovers[:5]))
            for o in leftovers:
                remember_alert(state, fingerprint(o), 3)
        deal_buttons = [{"action": "view", "label": f"{icon} {word} deal", "url": heroes[cat]["source_url"]}
                        for cat, icon, word in (("energy", "⚡", "Energy"), ("snack", "🍫", "Snack"), ("rtd", "🥤", "Shake"))
                        if heroes.get(cat)]
        payloads.append({"title": "📡 Deal Radar digest", "message": "\n".join(lines), "priority": 3,
                         "tags": ["satellite"], "click": app_url,
                         "actions": (deal_buttons or [{"action": "view", "label": "Open app", "url": app_url}])[:3]})
    return payloads[:cap]


def send(payloads: list[dict[str, Any]], cfg: Config, *, dry: bool) -> list[str]:
    """Returns a short log of what happened. Prints payloads when dry/no topic."""
    out = []
    topic = cfg.ntfy_topic
    server = cfg.settings["notify"]["server"]
    for p in payloads:
        body = {"topic": topic or "<NTFY_TOPIC>", "markdown": True, **p}
        if dry or not topic:
            safe = dict(body, topic="<NTFY_TOPIC>")
            print("[ntfy mock] " + json.dumps(safe, ensure_ascii=False))
            out.append(f"mock: {p['title']}")
            continue
        for attempt in range(3):
            try:
                r = requests.post(server, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                  headers={"Content-Type": "application/json"}, timeout=15)
                if r.status_code < 300:
                    out.append(f"sent: {p['title']}")
                    break
                log.warning("ntfy HTTP %s", r.status_code)
            except requests.RequestException as e:
                log.warning("ntfy error: %s", type(e).__name__)
            time.sleep(2 ** attempt)
        else:
            out.append(f"FAILED: {p['title']}")
    return out
