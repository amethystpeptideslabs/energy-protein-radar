"""Pass 2 — Extraction. A cheap model turns the dossier into strict JSON via
output_config.format (structured outputs; no citations, no beta header). It only copies raw
numbers; Python does all math. Schema uses no nullable unions (API limit is 16): unknown
numbers are 0, unknown strings are ""."""
from __future__ import annotations

import json
import logging
from typing import Any

from .config import Config
from .cost import CostTracker

log = logging.getLogger("radar.extract")

PROMO_ENUM = ["none", "pct_off", "amount_off", "bogo_50", "bogo_free", "fixed_unit_price", "multi_buy"]

OFFER_FIELDS: dict[str, dict[str, Any]] = {
    "product_id": {"type": "string"},  # enum filled per call
    "retailer": {"type": "string", "description": "Store selling it (not the deal site)."},
    "source_url": {"type": "string", "description": "Copied EXACTLY from ALLOWED_URLS."},
    "evidence_text": {"type": "string", "description": "Verbatim price/promo text from the dossier."},
    "evidence_date": {"type": "string", "description": "YYYY-MM-DD the source was posted/updated, or ''."},
    "pack_count": {"type": "integer", "description": "Units (cans/bars/bottles) in the priced pack."},
    "pack_price": {"type": "number", "description": "Price of ONE pack before promo/coupon/subscribe discounts."},
    "regular_pack_price": {"type": "number", "description": "Non-sale list/was price of one pack if shown, else 0."},
    "is_sale_price": {"type": "boolean", "description": "True if pack_price is a temporary sale/rollback price."},
    "unit_size_oz": {"type": "number", "description": "Fluid oz per can/bottle (drinks) or net wt oz (snacks); 0 if unknown."},
    "label_protein_g": {"type": "number", "description": "Protein g per unit from label/specs if stated, else 0."},
    "promo_type": {"type": "string", "enum": PROMO_ENUM},
    "promo_value": {"type": "number", "description": "pct_off: percent; amount_off: $ off order; fixed_unit_price: $ per unit; multi_buy: total $ for min_qty packs; else 0."},
    "min_qty": {"type": "integer", "description": "Packs required to trigger the promo (multi_buy count); 1 if none."},
    "code": {"type": "string", "description": "Promo code text or ''."},
    "code_pct_off": {"type": "number", "description": "Percent off from the code, else 0."},
    "code_amount_off": {"type": "number", "description": "Dollars off from the code, else 0."},
    "code_stackable": {"type": "boolean", "description": "True only if the source says the code stacks with the promo."},
    "subscribe_save_pct": {"type": "number", "description": "Subscribe & Save / Auto-Delivery percent, else 0."},
    "coupon_clip_value": {"type": "number", "description": "Clip coupon dollars, else 0."},
    "shipping_cost": {"type": "number", "description": "Shipping $ at this cart size, 0 if free/unknown/in-store."},
    "free_shipping_min": {"type": "number", "description": "Order $ for free shipping, else 0."},
    "in_store_only": {"type": "boolean"},
    "limit_per_customer": {"type": "integer", "description": "Max units per customer, 0 if none."},
    "membership_required": {"type": "boolean"},
    "stock_note": {"type": "string", "description": "Store-level stock ONLY if the page states it, e.g. 'In stock at Target Mission Viejo (pickup today)'; else ''."},
    "starts": {"type": "string", "description": "YYYY-MM-DD or ''."},
    "ends": {"type": "string", "description": "YYYY-MM-DD or ''."},
}

DEAD_CODE_FIELDS = {
    "code": {"type": "string"},
    "retailer": {"type": "string"},
    "source_url": {"type": "string"},
    "reason": {"type": "string", "enum": ["expired", "invalid", "reported-dead"]},
}


def build_schema(product_ids: list[str]) -> dict[str, Any]:
    offer_props = json.loads(json.dumps(OFFER_FIELDS))
    offer_props["product_id"]["enum"] = sorted(product_ids)
    return {
        "type": "object",
        "properties": {
            "offers": {"type": "array", "items": {
                "type": "object", "properties": offer_props,
                "required": list(offer_props), "additionalProperties": False}},
            "dead_codes": {"type": "array", "items": {
                "type": "object", "properties": DEAD_CODE_FIELDS,
                "required": list(DEAD_CODE_FIELDS), "additionalProperties": False}},
        },
        "required": ["offers", "dead_codes"],
        "additionalProperties": False,
    }


EXTRACT_INSTRUCTIONS = """\
Convert the evidence dossier into JSON offers. Rules:
- One offer per distinct pack/price/promo at a retailer. Skip offers whose URL is not in
  ALLOWED_URLS (copy URLs exactly, character for character).
- Copy raw numbers only. NEVER compute per-unit prices, totals, or apply discounts.
- pack_price = price of ONE pack before any promo, code, coupon or subscribe discount.
  If the listed price is a sale/rollback, set is_sale_price=true and put the was/list price
  in regular_pack_price.
- "BOGO 50%" -> bogo_50; "buy one get one free" -> bogo_free; "$1 cans"/"$X each" promo
  price per unit -> fixed_unit_price with promo_value=X and pack_count=1; "3 for $10" ->
  multi_buy, min_qty=3, promo_value=10; "15% off" (auto, no code) -> pct_off.
- Subscribe & Save / Auto-Delivery percent goes in subscribe_save_pct (not promo).
- Membership stores (Costco, Sam's Club, GNC Pro Access) -> membership_required=true.
- Use 0 / "" / false for anything unknown. Dates as YYYY-MM-DD.
- Use the product_id the dossier assigns; if the item is not one of the catalog products
  (wrong size, powder, excluded line), omit it.
"""


def extract(cfg: Config, client: Any, tracker: CostTracker, dossier: str,
            urls: list[str], product_ids: list[str], today: str) -> dict[str, Any]:
    if not dossier.strip() or not product_ids:
        return {"offers": [], "dead_codes": []}
    model = cfg.settings["models"]["extract"]
    catalog = "\n".join(
        f"- {pid}: {cfg.products[pid].display_name} ({cfg.products[pid].unit_size_oz:g} oz "
        f"{cfg.products[pid].unit_label})" for pid in product_ids)
    user = (f"TODAY: {today}\n\nCATALOG:\n{catalog}\n\nALLOWED_URLS:\n" + "\n".join(urls)
            + "\n\nDOSSIER:\n" + dossier)
    resp = client.messages.create(
        model=model, max_tokens=int(cfg.settings["models"]["max_extract_tokens"]),
        system=EXTRACT_INSTRUCTIONS,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": build_schema(product_ids)}})
    tracker.add_usage(model, resp.usage)
    if resp.stop_reason == "max_tokens":
        log.warning("extraction hit max_tokens; output may be truncated")
    text = "".join(getattr(b, "text", "") for b in resp.content)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"extraction returned invalid JSON ({resp.stop_reason}): {e}") from e
    data.setdefault("offers", [])
    data.setdefault("dead_codes", [])
    return data
