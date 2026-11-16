"""Pass 1 — Research. Claude + the web search tool produce a plain-text evidence dossier.
We also collect every URL that actually came back in web_search_tool_result blocks: that
set is the provenance whitelist for Pass 2 / validation."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .config import CATEGORY_LABEL, Config, Product
from .cost import CostTracker
from .util import normalize_url

log = logging.getLogger("radar.research")


class WebSearchDisabled(RuntimeError):
    pass


@dataclass
class ResearchResult:
    label: str
    product_ids: list[str]
    dossier: str = ""
    urls: dict[str, str] = field(default_factory=dict)       # normalized -> original
    page_ages: dict[str, str] = field(default_factory=dict)  # normalized -> page_age
    searches: int = 0
    stop_reason: str = ""
    error: str = ""


DOSSIER_RULES = """\
You are the research pass of a deal-tracking system. Your ONLY job is to find current,
real offers and write an evidence dossier. Another program does every calculation.

Rules:
- Use the web_search tool. Every offer MUST cite a page URL that came back in your search
  results. Never invent or guess URLs, prices, codes or dates. Skip anything you can't source.
- Costco: use costco.com pages only (product pages, warehouse savings). Never use third-party
  Costco trackers or price apps (warehouserunner, costco97 and the like); they aren't accepted.
- Copy price text VERBATIM (e.g. "$29.99", "2 for $5", "BOGO 50%", "Save $3 with coupon").
- Do NOT compute per-unit prices, totals or discounts. Report raw numbers only.
- Report pack size exactly as listed (e.g. "12 x 16 fl oz cans", "box of 12 bars").
- Sizes are strict: a 12 oz can is NOT a 16 oz product. Flavors don't matter.
- Respect each product's exclusions (no powders, tubs, sticks, shots, hydration lines,
  gummies; no plant-based/vegan protein products except where the catalog says so).
- Codes: say who reported the code and when ("reported by Slickdeals on 2026-11-14").
  Never claim a code was tested. If a source says a code is expired/invalid, list it under
  DEAD CODES.
- Sales must be LIVE TODAY on the page you cite. Copy start/end dates when shown. Never report a
  sale whose end date has passed or that hasn't started yet. Deal posts (Slickdeals, Stack3d,
  Hip2Save...) older than 7 days don't count unless the retailer's page still shows the sale.
- Note restrictions: in-store only, membership required (Costco, Sam's Club, GNC Pro Access),
  per-customer limits, minimum quantity, subscribe/auto-delivery requirements, shipping cost
  and free-shipping minimums, start/end dates.
- Prices are pre-tax, US. Location: Orange County, CA (Anaheim Hills / North OC first). In-store deals must be valid
  at an Orange County store; note pickup availability.

Write one block per offer, exactly:

OFFER
product_id: <id from the catalog>
retailer: <store selling it>
url: <exact URL from your search results>
price_text: "<verbatim>"
regular_price_text: "<verbatim list/was price if shown, else none>"
pack: <units per pack and size>
promo: <mechanics, or none>
code: <code + who reported it and when, or none>
subscribe_save: <% if offered, else none>
coupon: <clip coupon value, else none>
shipping: <cost and free-shipping minimum, or in-store>
restrictions: <in-store only / membership / limit / min qty / none>
dates: <posted date; promo start/end if known>
label: <protein g per unit and size from label/specs if seen, else none>
END

After the offers, optionally:

DEAD CODES
- <code> | <retailer> | <url> | <expired|invalid|reported-dead>
END
"""


LOCAL_FOCUS = (" LOCAL FIRST: the buyer is in Orange County, CA (Anaheim Hills / North OC first) and prefers local pickup. Look for "
               "in-store deals and buy-online-pick-up-in-store at OC stores (Target, Walmart, Vitamin Shoppe, GNC, Costco, "
               "Sam's Club, Grocery Outlet weekly ads, Ralphs, Vons, Sprouts). In-store-only or store-specific promos must be "
               "valid at an Orange County store; name it in local_store when the page does. Ship-to-home deals are still fine.")
BRAND_RULE = {
    "energy": " Gym/performance brands only: never report {} or other mainstream soda-aisle energy drinks.",
    "snack": (" Real protein bars/snacks only (the tracked gym brands, 15g+ protein): never report {}, other "
              "candy-brand protein bars or grocery-aisle granola/snack bars."),
    "rtd": " Never report {}.",
}
VS_BOGO_FOCUS = (" Vitamin Shoppe runs Buy One, Get One 50% Off (BOGO) on energy-drink cases and protein bars "
                 "almost every week: always check its BOGO / sale pages for these products and report each BOGO "
                 "item as promo_type bogo_50 with the single-pack price (confirm the product page still shows the BOGO label).")
CASE_FOCUS = (" Priority: CASE / multi-pack prices (12-, 15-, 18-, 24-packs, boxes of bars) — the buyer "
              "buys by the case. Single-can/bottle promos (e.g. $1/can weekends) still count; report both." + LOCAL_FOCUS
              + VS_BOGO_FOCUS)


def catalog_text(products: list[Product]) -> str:
    lines = []
    for p in products:
        size = f"{p.unit_size_oz:g} fl oz" if p.is_drink else f"{p.unit_size_oz:g} oz"
        prot = f", {p.protein_g:g}g protein/{p.unit_label}" if p.protein_g else ""
        excl = ", ".join(p.exclude_terms[:8])
        pb = " (plant-based: allowed exception)" if p.plant_based else ""
        lines.append(f"- {p.id}: {p.display_name} — {size} per {p.unit_label}{prot}{pb}. "
                     f"Exclude: {excl}")
    return "\n".join(lines)


def build_system(cfg: Config, memory: dict[str, Any]) -> str:
    products = cfg.enabled()
    retail = cfg.settings.get("retailers", {})
    retail_lines = "\n".join(f"- {r['name']} ({', '.join(r['domains'])}): {r.get('playbook', '')}"
                             for r in retail.values())
    intel = "\n".join(f"- {i['name']} ({', '.join(i['domains'])}) {i.get('note', '')}"
                      for i in cfg.settings.get("deal_intel", []))
    refs = []
    for p in products:
        pm = memory["products"].get(p.id, {})
        atl = pm.get("all_time_low") or {}
        refs.append(f"- {p.id}: ref ${p.ref_unit_price if p.ref_unit_price is not None else '?'}"
                    f"/{p.unit_label}; record ${atl.get('unit_price', '?')} at {atl.get('retailer', '?')}")
    dead = "\n".join(f"- {d['code']} @ {d.get('retailer', '')} (until {d.get('skip_until')})"
                     for d in memory.get("dead_codes", [])) or "- none"
    return (DOSSIER_RULES
            + "\n\nPRODUCT CATALOG\n" + catalog_text(products)
            + "\n\nRETAILERS\n" + retail_lines
            + "\n\nDEAL-INTEL SOURCES\n" + intel
            + "\n\nCURRENT REFERENCE PRICES AND RECORDS (context only)\n" + "\n".join(refs)
            + "\n\nKNOWN DEAD CODES (ignore these)\n" + dead + "\n")


def _plan_line(p: Product, cfg: Config) -> str:
    names = [cfg.retailer_name(r) for r in p.retailers_priority]
    return (f"{p.id} ({p.display_name}). Try searches like: {'; '.join(p.search_terms)}. "
            f"Retailers to cover: {', '.join(names)}.")


def build_jobs(cfg: Config, mode: str, slot: str, only: str | None,
               today: date) -> list[tuple[str, list[str], str, int]]:
    """-> [(label, product_ids, user_prompt, max_uses)]"""
    r = cfg.settings["research"]
    day = today.strftime("%A %Y-%m-%d")
    products = [p for p in cfg.enabled() if not only or p.id == only]
    jobs = []
    if mode == "check":
        return [("check", [], "Use web_search exactly once to look up 'Ghost Energy 12 pack price'. "
                 "Reply with one short line naming one source. No OFFER blocks needed.", 1)]
    if mode in ("deep", "calibrate"):  # one job per product (API engine deep, calibrate)
        for p in products:
            extra = ""
            if mode == "calibrate":
                extra = ("\nCALIBRATION: for each major retailer also report the REGULAR (non-sale) "
                         "price in regular_price_text, and report label protein per unit and exact "
                         "size in `label` (nutrition facts / spec sheet).")
            jobs.append((p.id, [p.id],
                         f"Today is {day}. Research current offers for ONE product:\n{_plan_line(p, cfg)}\n"
                         f"Cover the retailers above plus the brand's own site and deal-intel sources.{CASE_FOCUS} "
                         f"Report every concrete sourced offer as OFFER blocks.{extra}",
                         int(r["calibrate_max_uses" if mode == "calibrate" else "deep_max_uses"])))
        return jobs
    # quick (morning) / midday / deep_cat: one call per category (energy can split / rotate)
    max_uses = int(r["midday_max_uses"] if slot == "midday" else r["quick_max_uses"])
    for cat in ("energy", "snack", "rtd"):
        ps = [p for p in products if p.category == cat]
        if not ps:
            continue
        focus = ("Focus: deal-intel posts from the last few days (Stack3d, Slickdeals, PricePlow, Hip2Save) and "
                 "the top retailers (Vitamin Shoppe, GNC, Amazon, Walmart, Target, Costco), including sales that "
                 "started TODAY (Target weekly deals start Sunday; Vons/Albertsons and Ralphs weekly ads start "
                 "Wednesday; Walmart rollbacks change any day).")
        focus += CASE_FOCUS
        if slot == "midday" and mode == "quick":
            focus = ("Focus: NEW sales that went live TODAY or since this morning's scan: Vitamin Shoppe / GNC "
                     "BOGO 50% and sale pages, THIS WEEKEND's in-store $1/can energy events (usually start "
                     "Thursday, sometimes Friday), Target weekly deals, Vons/Albertsons and Ralphs weekly ads, "
                     "Walmart rollbacks/clearance, and Stack3d / Slickdeals posts from the last 24 hours." + CASE_FOCUS)
        brands = sorted({b for p in ps for b in p.exclude_brands})
        if brands:
            focus += BRAND_RULE[cat].format(", ".join(b.title() for b in brands))
        for label, group, others in _category_groups(cat, ps, mode, slot, r, today):
            lines = "\n".join(f"- {_plan_line(p, cfg)}" for p in group)
            also = (f"\nAlso report any deal you come across for the other tracked {CATEGORY_LABEL[cat]} "
                    f"brands: {', '.join(f'{p.id} ({p.display_name})' for p in others)}.") if others else ""
            jobs.append((label, [p.id for p in group + others],
                         f"Today is {day}. Find the best CURRENT deals for these {CATEGORY_LABEL[cat]} "
                         f"products:\n{lines}{also}\n{focus}\nPrioritize the biggest discounts. Report every "
                         f"concrete sourced offer as OFFER blocks.", max_uses))
    return jobs


def _category_groups(cat: str, ps: list[Product], mode: str, slot: str, r: dict[str, Any],
                     today: date) -> list[tuple[str, list[Product], list[Product]]]:
    """-> [(label, products to research, other products to report if seen)].
    Big categories (energy, snacks): quick runs focus on a rotating slice (every product gets a
    focused look every few days; store-wide promos still get reported for all of them), and deep
    runs split the category into several jobs so each product gets real search attention."""
    if mode == "deep_cat":
        n = max(1, int(r.get("deep_jobs", {}).get(cat, 1)))
        if n == 1:
            return [(cat, ps, [])]
        return [(f"{cat}-{i + 1}", ps[i::n], []) for i in range(n) if ps[i::n]]
    n = max(1, int(r.get("focus_groups", {}).get(cat, 1)))
    if n == 1 or slot == "midday":
        return [(cat, ps, [])]
    i = today.toordinal() % n
    group = ps[i::n]
    return [(cat, group, [p for p in ps if p not in group])]


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def collect_urls(blocks: list[dict[str, Any]], result: ResearchResult) -> None:
    for b in blocks:
        if b.get("type") == "web_search_tool_result":
            content = b.get("content")
            if isinstance(content, dict) and content.get("type") == "web_search_tool_result_error":
                log.warning("search error in %s: %s", result.label, content.get("error_code"))
                continue
            for item in _walk(content):
                if item.get("type") == "web_search_result" and item.get("url"):
                    n = normalize_url(item["url"])
                    result.urls.setdefault(n, item["url"])
                    if item.get("page_age"):
                        result.page_ages.setdefault(n, item["page_age"])
        elif b.get("type") == "text":
            result.dossier += b.get("text", "")
            for c in b.get("citations") or []:
                if c.get("type") == "web_search_result_location" and c.get("url"):
                    result.urls.setdefault(normalize_url(c["url"]), c["url"])


class Researcher:
    def __init__(self, cfg: Config, client: Any, tracker: CostTracker, model: str):
        self.cfg = cfg
        self.client = client
        self.tracker = tracker
        self.model = model
        m = cfg.settings["models"]
        self.tool_version = m["web_search_tool"]
        self.fallback = False

    def _tool(self, max_uses: int) -> dict[str, Any]:
        loc = {k: v for k, v in self.cfg.settings["location"].items() if v}
        if self.fallback:
            return {"type": self.cfg.settings["models"]["web_search_fallback"], "name": "web_search",
                    "max_uses": max_uses, "user_location": loc, "allowed_callers": ["direct"]}
        return {"type": self.tool_version, "name": "web_search", "max_uses": max_uses,
                "user_location": loc}

    def run(self, label: str, product_ids: list[str], system: str, user: str,
            max_uses: int) -> ResearchResult:
        import anthropic

        result = ResearchResult(label=label, product_ids=product_ids)
        m = self.cfg.settings["models"]
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        container = None
        for attempt in range(int(m["max_pause_continuations"]) + 1):
            kwargs: dict[str, Any] = dict(
                model=self.model, max_tokens=int(m["max_research_tokens"]),
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages, tools=[self._tool(max_uses)])
            if container:
                kwargs["container"] = container
            try:
                resp = self.client.messages.create(**kwargs)
            except anthropic.BadRequestError as e:
                msg = str(e).lower()
                if "web search" in msg and ("not enabled" in msg or "disabled" in msg):
                    raise WebSearchDisabled(str(e)) from e
                if not self.fallback and attempt == 0 and any(
                        k in msg for k in ("allowed_callers", "programmatic", "code_execution", "dynamic")):
                    log.warning("dynamic filtering unavailable for %s; falling back to direct search", self.model)
                    self.fallback = True
                    continue
                raise
            self.tracker.add_usage(self.model, resp.usage)
            stu = getattr(resp.usage, "server_tool_use", None)
            result.searches += int(getattr(stu, "web_search_requests", 0) or 0) if stu else 0
            blocks = [b.model_dump() if hasattr(b, "model_dump") else dict(b) for b in resp.content]
            collect_urls(blocks, result)
            result.stop_reason = resp.stop_reason or ""
            if getattr(resp, "container", None) is not None:
                container = getattr(resp.container, "id", None) or container
            if resp.stop_reason == "pause_turn":
                messages = messages + [{"role": "assistant", "content": resp.content}]
                continue
            break
        return result


def dump_debug(results: list[ResearchResult]) -> str:
    return json.dumps([{"label": r.label, "urls": len(r.urls), "searches": r.searches,
                        "stop": r.stop_reason, "chars": len(r.dossier), "error": r.error}
                       for r in results], indent=1)
