"""ALL price math lives here. The model only extracts raw numbers; Python builds the
cheapest valid cart that triggers each promo and computes every derived price.

Stacking order (conservative where retailers differ):
  packs x pack_price -> promo (or code if non-stackable and cheaper) -> stackable code
  -> clip coupon (once per order) -> subscribe/auto-delivery % -> shipping (if under
  free-shipping minimum and not in-store) -> CA CRV per container. Pre-tax.
"""
from __future__ import annotations

import re

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from .config import Product
from .tiers import (UNRATED, energy_tier, protein_tier, protein_value_badge)
from .util import cents, money

PROMO_TYPES = ("none", "pct_off", "amount_off", "bogo_50", "bogo_free",
               "fixed_unit_price", "multi_buy")
ZERO = Decimal("0")


@dataclass
class Cart:
    packs: int
    units: int
    steps: list[str] = field(default_factory=list)
    used_code: bool = False
    used_promo: bool = False
    subtotal_before_crv: Decimal = ZERO
    crv_total: Decimal = ZERO
    shipping: Decimal = ZERO
    total: Decimal = ZERO


def _num(o: dict[str, Any], key: str) -> Decimal:
    v = o.get(key)
    if v in (None, ""):
        return ZERO
    try:
        return money(v)
    except Exception:  # noqa: BLE001 - bad model value -> treat as absent
        return ZERO


def _int(o: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(o.get(key) or default)
    except (TypeError, ValueError):
        return default


def _packs_needed(o: dict[str, Any]) -> int:
    promo = o.get("promo_type") or "none"
    min_qty = max(1, _int(o, "min_qty", 1))
    if promo in ("bogo_50", "bogo_free"):
        n = max(2, min_qty)
        return n + (n % 2)  # whole pairs
    return min_qty


def _apply_promo(promo: str, v: Decimal, pack_price: Decimal, packs: int,
                 pack_count: int) -> tuple[Decimal, str]:
    base = pack_price * packs
    if promo == "pct_off" and v > 0:
        return base * (1 - v / 100), f"{v.normalize()}% off auto-applies"
    if promo == "amount_off" and v > 0:
        return max(ZERO, base - v), f"${cents(v)} off auto-applies"
    if promo == "bogo_50":
        pairs, rest = divmod(packs, 2)
        return pack_price * (Decimal("1.5") * pairs + rest), "BOGO 50% auto-applies"
    if promo == "bogo_free":
        pairs, rest = divmod(packs, 2)
        return pack_price * (pairs + rest), "BOGO free auto-applies"
    if promo == "fixed_unit_price" and v > 0:
        return v * packs * pack_count, f"promo price ${cents(v)}/unit"
    if promo == "multi_buy" and v > 0:
        return v, f"{packs} for ${cents(v)}"
    return base, ""


def _apply_code(amount: Decimal, o: dict[str, Any]) -> Decimal:
    pct, off = _num(o, "code_pct_off"), _num(o, "code_amount_off")
    if pct > 0:
        amount = amount * (1 - pct / 100)
    if off > 0:
        amount = max(ZERO, amount - off)
    return amount


def build_cart(o: dict[str, Any], product: Product, crv_cfg: dict[str, Any]) -> Cart:
    pack_price = _num(o, "pack_price")
    pack_count = max(1, _int(o, "pack_count", 1))
    promo = o.get("promo_type") or "none"
    if promo not in PROMO_TYPES:
        promo = "none"
    v = _num(o, "promo_value")
    packs = _packs_needed(o)
    cart = Cart(packs=packs, units=packs * pack_count)
    unit_word = product.unit_label.split(" ")[0]
    cart.steps.append(f"Add {packs}× {pack_count}-{unit_word} pack (${cents(pack_price)} each)"
                      if pack_count > 1 else f"Add {packs}× {unit_word} (${cents(pack_price)} each)")

    base = pack_price * packs
    promo_amt, promo_desc = _apply_promo(promo, v, pack_price, packs, pack_count)
    code = (o.get("code") or "").strip()
    has_code_value = code and (_num(o, "code_pct_off") > 0 or _num(o, "code_amount_off") > 0)

    if promo != "none" and promo_desc:
        if has_code_value and o.get("code_stackable"):
            amt = _apply_code(promo_amt, o)
            cart.used_promo = cart.used_code = True
            cart.steps.append(f"{promo_desc} → ${cents(promo_amt)}")
            cart.steps.append(f"Code {code} (stacks) → ${cents(amt)}")
        elif has_code_value:
            code_only = _apply_code(base, o)
            if code_only < promo_amt:
                amt, cart.used_code = code_only, True
                cart.steps.append(f"Code {code} (better than the non-stackable promo) → ${cents(amt)}")
            else:
                amt, cart.used_promo = promo_amt, True
                cart.steps.append(f"{promo_desc} → ${cents(amt)} (skip code {code}; doesn't stack)")
        else:
            amt, cart.used_promo = promo_amt, True
            cart.steps.append(f"{promo_desc} → ${cents(amt)}")
    elif has_code_value:
        amt, cart.used_code = _apply_code(base, o), True
        cart.steps.append(f"Code {code} → ${cents(amt)}")
    else:
        amt = base

    clip = _num(o, "coupon_clip_value")
    if clip > 0:
        amt = max(ZERO, amt - clip)
        cart.steps.append(f"Clip ${cents(clip)} coupon → ${cents(amt)}")

    sns = _num(o, "subscribe_save_pct")
    if sns > 0:
        amt = amt * (1 - sns / 100)
        cart.steps.append(f"Choose Subscribe/Auto-Delivery {sns.normalize()}% → ${cents(amt)}")

    ship = _num(o, "shipping_cost")
    free_min = _num(o, "free_shipping_min")
    if ship > 0 and not o.get("in_store_only") and (free_min == 0 or amt < free_min):
        cart.shipping = ship
        amt += ship
        cart.steps.append(f"Shipping +${cents(ship)}")

    cart.subtotal_before_crv = amt
    if product.crv_applies and 0 < product.unit_size_oz < float(crv_cfg["under_oz"]):
        cart.crv_total = money(crv_cfg["per_container_usd"]) * cart.units
        cart.steps.append(f"CA CRV +${cents(cart.crv_total)}")
    cart.total = max(ZERO, amt + cart.crv_total)
    return cart


def price_offer(o: dict[str, Any], product: Product, ref: float | None,
                settings: dict[str, Any]) -> dict[str, Any]:
    """Returns computed fields; never mutates the input."""
    cart = build_cart(o, product, settings["crv"])
    units = Decimal(cart.units)
    unit_price = cents(cart.total / units)
    unit_ex_crv = cents((cart.total - cart.crv_total) / units)
    size = money(product.unit_size_oz) if product.unit_size_oz else None
    per_oz = cents(unit_price / size) if (size and product.is_drink) else None
    per_10g = cents(unit_price / money(product.protein_g) * 10) if product.protein_g else None
    pct = (unit_ex_crv / money(ref) * 100).quantize(Decimal("0.1")) if ref else None

    if product.is_energy:
        tier = energy_tier(unit_price, product.unit_size_oz, settings["tiers"]["energy"])
    else:
        tier = protein_tier(pct, settings["tiers"]["protein"]) if pct is not None else UNRATED

    unit_word = product.unit_label.split(" ")[0]
    cart.steps.append(f"Expected ${cents(cart.total)} → ${unit_price}/{unit_word}"
                      + (f" (${per_10g}/10g protein)" if per_10g is not None else ""))
    return {
        "packs_in_cart": cart.packs,
        "units_in_cart": cart.units,
        "effective_pack_total": float(cents(cart.total)),
        "unit_price": float(unit_price),
        "unit_price_ex_crv": float(unit_ex_crv),
        "price_per_oz": float(per_oz) if per_oz is not None else None,
        "price_per_10g_protein": float(per_10g) if per_10g is not None else None,
        "pct_vs_ref": float(pct) if pct is not None else None,
        "tier": tier,
        "protein_value_badge": protein_value_badge(per_10g, settings["tiers"]["protein_value"])
        if per_10g is not None else "",
        "crv_total": float(cents(cart.crv_total)),
        "shipping_included": float(cents(cart.shipping)),
        "used_code": cart.used_code,
        "used_promo": cart.used_promo,
        "is_case": max(1, _int(o, "pack_count", 1)) >= int(settings.get("research", {}).get("case_min_units", 12)),
        "playbook": cart.steps,
    }


def regular_unit_price(o: dict[str, Any]) -> Decimal | None:
    """Regular (non-promo) per-unit shelf price for ref calibration, or None if this offer
    can't tell us one. Sale prices never qualify."""
    count = max(1, _int(o, "pack_count", 1))
    reg = _num(o, "regular_pack_price")
    if reg > 0:
        return cents(reg / count)
    promo = o.get("promo_type") or "none"
    if promo == "none" and not (o.get("code") or "").strip() and _num(o, "coupon_clip_value") == 0 \
            and _num(o, "subscribe_save_pct") == 0 and not o.get("is_sale_price"):
        p = _num(o, "pack_price")
        return cents(p / count) if p > 0 else None
    return None


UNAVAILABLE_RE = re.compile(r"out of stock|unavailable|discontinued|sold out", re.I)


def is_unavailable(offer: dict[str, Any]) -> bool:
    """A store check said you can't get it now (out of stock locally / discontinued)."""
    return bool(UNAVAILABLE_RE.search(offer.get("stock_note") or ""))


def rank_key(offer: dict[str, Any]) -> tuple:
    """Lower is better. Confirmed-unavailable deals (out of stock at the OC store, discontinued)
    go last. Then energy: tier, local-first, $/can. Protein: tier, local-first, % of ref
    (biggest discount first), then $/10g protein as tiebreak."""
    from .tiers import TIER_RANK
    gone = 1 if is_unavailable(offer) else 0
    tier_rank = TIER_RANK.get(offer.get("tier", UNRATED), 9)
    not_local = 0 if offer.get("fulfillment") in ("in_store", "pickup") else 1
    if offer.get("category") == "energy":
        return (gone, tier_rank, not_local, offer.get("unit_price") or 999.0, 0.0)
    pct = offer.get("pct_vs_ref")
    return (gone, tier_rank, not_local, pct if pct is not None else 999.0,
            offer.get("price_per_10g_protein") or 999.0)


def as_dict(c: Cart) -> dict[str, Any]:
    return asdict(c)
