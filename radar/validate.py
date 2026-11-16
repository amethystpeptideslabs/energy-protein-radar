"""Provenance, freshness and sanity checks. Drops bad offers with a reason; flags
too-good-to-be-true prices as UNVERIFIED (shown in app, never pushed, never a record)."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .config import Config
from .util import normalize_url, parse_date, url_host

SIZE_RE = re.compile(r"(\d{1,2}(?:\.\d)?)\s*-?\s*(?:fl\.?\s*)?oz\b", re.I)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def resolve_retailer(name: str, url: str, settings: dict[str, Any]) -> tuple[str, str]:
    """-> (retailer_key, source_kind). Matches the source URL's domain first, then the name."""
    host = url_host(url)
    retailers = settings.get("retailers", {})
    for key, r in retailers.items():
        if any(host == d or host.endswith("." + d) for d in r.get("domains", [])):
            return key, "retailer"
    kind = "other"
    for intel in settings.get("deal_intel", []):
        if any(host == d or host.endswith("." + d) for d in intel.get("domains", [])):
            kind = "deal_intel"
    n = _slug(name or "")
    for key, r in retailers.items():
        if n and (n == key or n == _slug(r["name"]) or _slug(r["name"]).startswith(n)
                  or n.startswith(key)):
            return key, kind
    return (n or host or "unknown"), kind


ONLINE_WORDS = re.compile(r"online|ships?\b|shipping|nationwide|all stores|website", re.I)
ZIP_RE = re.compile(r"(?<!\d)(\d{5})(?!\d)")


def _host_in(host: str, domains: list[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def in_area(place: str, area: dict[str, Any]) -> bool:
    """True if a store location string names a city or ZIP inside the shopping area."""
    text = place.lower()
    for city in area.get("cities", []):
        if re.search(r"(?<![a-z])" + re.escape(city.lower()) + r"(?![a-z])", text):
            return True
    prefixes = [str(z) for z in area.get("zip_prefixes", [])]
    return any(z.startswith(p) for z in ZIP_RE.findall(place) for p in prefixes)


def area_check(o: dict[str, Any], retailer_key: str, settings: dict[str, Any]) -> str:
    """Shopping-area rule. In-store prices must be at a store in the area; online deals that
    ship to the area count from anywhere. Returns a drop detail, or '' to keep. May set
    o['in_store_only'] for warehouse-price trackers."""
    area = settings.get("area") or {}
    if not area:
        return ""
    name = area.get("name", "the shopping area")
    host = url_host(o.get("source_url", ""))
    if _host_in(host, area.get("out_of_area_domains", [])):
        return f"{host} has no stores in {name} and doesn't ship there"
    if _host_in(host, area.get("warehouse_trackers", [])):
        o["in_store_only"] = True
    loc = str(o.get("store_location") or "").strip()
    if loc and not ONLINE_WORDS.search(loc) and not in_area(loc, area):
        return f"store '{loc}' is outside {name}"
    if o.get("in_store_only"):
        if retailer_key not in area.get("in_store_retailers", []):
            return f"in-store price at a chain with no stores in {name}"
        if retailer_key in area.get("store_price_varies", []) and (not loc or ONLINE_WORDS.search(loc)):
            return f"warehouse price not confirmed at a store in {name}"
    return ""


def _term_hit(text: str, terms: list[str]) -> str | None:
    for t in terms:
        if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", text):
            return t
    return None


def build_url_index(urls: dict[str, str]) -> tuple[set[str], set[str]]:
    """urls: normalized -> original. Returns (full set, host+path set)."""
    full = set(urls)
    loose = {u.split("?", 1)[0] for u in urls}
    return full, loose


def is_sourced(url: str, index: tuple[set[str], set[str]]) -> bool:
    n = normalize_url(url)
    return bool(n) and (n in index[0] or n.split("?", 1)[0] in index[1])


def validate_offers(raw: list[dict[str, Any]], cfg: Config, url_map: dict[str, str],
                    page_ages: dict[str, str], dead_codes: list[dict[str, Any]],
                    today: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    vcfg = cfg.settings["validation"]
    stale_cutoff = today - timedelta(days=int(vcfg["stale_days"]))
    index = build_url_index(url_map)
    dead = {(d["code"].upper(), d.get("retailer", "")): d for d in dead_codes
            if (parse_date(d.get("skip_until")) or today) >= today}
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    seen: set[tuple] = set()

    def drop(o: dict[str, Any], reason: str, detail: str = "") -> None:
        dropped.append({**o, "drop_reason": reason, "drop_detail": detail})

    for o in raw:
        o = dict(o)
        product = cfg.products.get(o.get("product_id", ""))
        if not product or not product.enabled:
            drop(o, "wrong_product", "unknown or disabled product_id")
            continue
        url = o.get("source_url", "")
        if not is_sourced(url, index):
            drop(o, "unsourced", "source_url not in this run's web_search results")
            continue
        o["source_url"] = url_map.get(normalize_url(url), url)
        try:
            pack_price = float(o.get("pack_price") or 0)
        except (TypeError, ValueError):
            pack_price = 0.0
        if pack_price <= 0:
            drop(o, "no_price", "no usable price")
            continue

        text = " ".join(str(o.get(k, "")) for k in ("evidence_text", "title")).lower()
        hit = _term_hit(text, product.exclude_terms)
        if hit:
            drop(o, "wrong_product", f"excluded term '{hit}'")
            continue
        tol = float(vcfg["size_tolerance_oz"])
        stated = float(o.get("unit_size_oz") or 0)
        if product.is_drink:
            if stated and not product.accepts_size(stated, tol):
                drop(o, "wrong_product", f"size {stated}oz ≠ {product.unit_size_oz}oz")
                continue
            if not stated:
                sizes = [float(s) for s in SIZE_RE.findall(text) if 6 <= float(s) <= 40]
                if sizes and not any(product.accepts_size(s, tol) for s in sizes):
                    drop(o, "wrong_product", f"size {sizes[0]}oz ≠ {product.unit_size_oz}oz")
                    continue

        ends = parse_date(o.get("ends"))
        if ends and ends < today:
            drop(o, "stale", f"promo ended {ends}")
            continue
        ev = parse_date(o.get("evidence_date")) or parse_date(page_ages.get(normalize_url(url), ""))
        if ev and ev < stale_cutoff and not (ends and ends >= today):
            drop(o, "stale", f"evidence from {ev}")
            continue
        o["evidence_date"] = ev.isoformat() if ev else ""

        retailer_key, kind = resolve_retailer(o.get("retailer", ""), o["source_url"], cfg.settings)
        o["retailer_key"], o["source_kind"] = retailer_key, kind
        o["retailer_name"] = cfg.retailer_name(retailer_key) if retailer_key in \
            cfg.settings.get("retailers", {}) else (o.get("retailer") or retailer_key)
        outside = area_check(o, retailer_key, cfg.settings)
        if outside:
            drop(o, "outside_area", outside)
            continue
        o["store_location"] = str(o.get("store_location") or "").strip()
        code = (o.get("code") or "").strip()
        if code and ((code.upper(), retailer_key) in dead or (code.upper(), "") in dead):
            drop(o, "dead_code", f"code {code} is on the dead list")
            continue
        r = cfg.settings.get("retailers", {}).get(retailer_key, {})
        if r.get("membership"):
            o["membership_required"] = True

        fp = (o["product_id"], retailer_key, normalize_url(o["source_url"]), code.upper(),
              int(o.get("pack_count") or 1), round(pack_price, 2), o.get("promo_type", "none"))
        if fp in seen:
            continue
        seen.add(fp)
        kept.append(o)
    return kept, dropped


def flag_unverified(priced: list[dict[str, Any]], cfg: Config) -> None:
    """Energy below $0.75/can or protein below 50% of ref needs a second independent
    source (different domain, within 5%) or it is flagged UNVERIFIED."""
    vcfg = cfg.settings["validation"]
    tol = float(vcfg["second_source_tolerance_pct"]) / 100
    for o in priced:
        cat = o["category"]
        suspicious = (cat == "energy" and o["unit_price"] < float(vcfg["unverified_energy_below"])) or \
                     (cat != "energy" and o.get("pct_vs_ref") is not None
                      and o["pct_vs_ref"] < float(vcfg["unverified_protein_below_pct"]))
        o["unverified"] = False
        if not suspicious:
            continue
        host = url_host(o["source_url"])
        corroborated = any(
            p is not o and p["product_id"] == o["product_id"] and url_host(p["source_url"]) != host
            and abs(p["unit_price"] - o["unit_price"]) <= tol * o["unit_price"]
            for p in priced)
        o["unverified"] = not corroborated


def dead_codes_from_reports(reports: list[dict[str, Any]], url_map: dict[str, str],
                            cfg: Config, today: date) -> list[dict[str, Any]]:
    """Sources saying a code is expired/invalid -> dead_codes entries (+60 days)."""
    index = build_url_index(url_map)
    days = int(cfg.settings["validation"]["dead_code_skip_days"])
    out = []
    for r in reports:
        code = (r.get("code") or "").strip()
        if not code or not is_sourced(r.get("source_url", ""), index):
            continue
        key, _ = resolve_retailer(r.get("retailer", ""), r.get("source_url", ""), cfg.settings)
        out.append({"code": code, "retailer": key,
                    "reason": r.get("reason") if r.get("reason") in ("expired", "invalid", "reported-dead")
                    else "reported-dead",
                    "first_seen_dead": today.isoformat(),
                    "skip_until": (today + timedelta(days=days)).isoformat()})
    return out
