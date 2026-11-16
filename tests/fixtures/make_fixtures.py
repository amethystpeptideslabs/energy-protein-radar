"""Regenerates the dry-run fixtures (synthetic, for tests only — not real offers)."""
import json
from pathlib import Path

D = dict(regular_pack_price=0, is_sale_price=False, unit_size_oz=0, label_protein_g=0,
         promo_type="none", promo_value=0, min_qty=1, code="", code_pct_off=0, code_amount_off=0,
         code_stackable=False, subscribe_save_pct=0, coupon_clip_value=0, shipping_cost=0,
         free_shipping_min=0, in_store_only=False, limit_per_customer=0, membership_required=False,
         starts="", ends="", evidence_date="2026-11-14")


def offer(**kw):
    o = dict(D)
    o.update(kw)
    return o


FIX = {
 "energy": {
  "label": "energy", "searches": 8,
  "product_ids": ["ghost-energy-16", "3d-energy-16", "gorilla-mind-energy-16", "bum-energy-12",
                  "celsius-essentials-16", "celsius-original-12", "bang-16"],
  "urls": ["https://www.stack3d.com/2026/11/vitamin-shoppe-1-dollar-energy-weekend.html",
           "https://www.amazon.com/dp/B0FIXTURE01",
           "https://www.walmart.com/ip/Bang-Energy-16oz-12pk/000000001",
           "https://www.costco.com/celsius-24-pack.product.000000001.html",
           "https://www.gnc.com/ghost/fixture-gorilla-mind-energy.html",
           "https://www.vitaminshoppe.com/p/bum-energy-12oz-12pk/fx1",
           "https://www.target.com/p/celsius-essentials/-/A-00000001",
           "https://www.ghostlifestyle.com/products/ghost-hydration",
           "https://slickdeals.net/f/00000001-ghost-code-expired"],
  "page_ages": {"https://www.vitaminshoppe.com/p/bum-energy-12oz-12pk/fx1": "October 1, 2026"},
  "extraction": {"offers": [
    offer(product_id="ghost-energy-16", retailer="The Vitamin Shoppe",
          source_url="https://www.stack3d.com/2026/11/vitamin-shoppe-1-dollar-energy-weekend.html",
          evidence_text="Ghost Energy 16 oz cans $1 each in-store, limit 6, Thu-Sun",
          pack_count=1, pack_price=2.99, unit_size_oz=16, promo_type="fixed_unit_price", promo_value=1.00,
          in_store_only=True, limit_per_customer=6, evidence_date="2026-11-13", starts="2026-11-13", ends="2026-11-16"),
    offer(product_id="ghost-energy-16", retailer="Amazon", source_url="https://www.amazon.com/dp/B0FIXTURE01",
          evidence_text="Ghost Energy 16 fl oz (Pack of 12) $29.99, Save $3.00 with coupon, Subscribe & Save 15%",
          pack_count=12, pack_price=29.99, unit_size_oz=16, coupon_clip_value=3, subscribe_save_pct=15),
    offer(product_id="bang-16", retailer="Walmart", source_url="https://www.walmart.com/ip/Bang-Energy-16oz-12pk/000000001",
          evidence_text="Bang Energy 16 oz 12 pack $21.48", pack_count=12, pack_price=21.48, unit_size_oz=16),
    offer(product_id="celsius-original-12", retailer="Costco", source_url="https://www.costco.com/celsius-24-pack.product.000000001.html",
          evidence_text="Celsius 12 fl oz, 24-count $27.99", pack_count=24, pack_price=27.99, unit_size_oz=12,
          membership_required=True),
    offer(product_id="gorilla-mind-energy-16", retailer="GNC", source_url="https://www.gnc.com/ghost/fixture-gorilla-mind-energy.html",
          evidence_text="Gorilla Mind Energy 16oz 12pk $35.99 BOGO 50%", pack_count=12, pack_price=35.99,
          unit_size_oz=16, promo_type="bogo_50"),
    offer(product_id="3d-energy-16", retailer="Amazon", source_url="https://www.amazon.com/dp/NOT-IN-SEARCH-RESULTS",
          evidence_text="3D Energy 16oz 12 pack $19.99", pack_count=12, pack_price=19.99, unit_size_oz=16),
    offer(product_id="bum-energy-12", retailer="The Vitamin Shoppe", source_url="https://www.vitaminshoppe.com/p/bum-energy-12oz-12pk/fx1",
          evidence_text="Bum Energy 12oz 12 pack BOGO 50%", pack_count=12, pack_price=26.99, unit_size_oz=12,
          promo_type="bogo_50", evidence_date="2026-10-01"),
    offer(product_id="celsius-essentials-16", retailer="Target", source_url="https://www.target.com/p/celsius-essentials/-/A-00000001",
          evidence_text="Celsius Essentials 12 fl oz 12pk $19.99", pack_count=12, pack_price=19.99, unit_size_oz=12),
    offer(product_id="ghost-energy-16", retailer="Ghost", source_url="https://www.ghostlifestyle.com/products/ghost-hydration",
          evidence_text="Ghost Hydration sticks 20 servings $24.99", pack_count=1, pack_price=24.99),
  ], "dead_codes": [{"code": "GHOST20", "retailer": "Ghost", "source_url": "https://slickdeals.net/f/00000001-ghost-code-expired", "reason": "expired"}]}},
 "snack": {
  "label": "snack", "searches": 8,
  "product_ids": ["built-puff", "barebells", "magic-spoon-pastry", "drumroll-donuts", "prime-bites",
                  "legendary-pastry", "legendary-donuts", "legendary-chips", "quest-chips"],
  "urls": ["https://www.costco.com/barebells-18-count.product.000000002.html",
           "https://www.amazon.com/dp/B0FIXTURE02", "https://www.target.com/p/quest-chips/-/A-00000002",
           "https://www.ralphs.com/p/drumroll-mini-donuts/0000000000003",
           "https://eatlegendary.com/products/protein-pastry", "https://www.walmart.com/ip/magic-spoon-pastry/000000004"],
  "extraction": {"offers": [
    offer(product_id="barebells", retailer="Costco", source_url="https://www.costco.com/barebells-18-count.product.000000002.html",
          evidence_text="Barebells Protein Bar 18-count $29.99", pack_count=18, pack_price=29.99, label_protein_g=20,
          membership_required=True),
    offer(product_id="built-puff", retailer="Amazon", source_url="https://www.amazon.com/dp/B0FIXTURE02",
          evidence_text="Built Puff 12 bars $27.99, Subscribe & Save 15%", pack_count=12, pack_price=27.99,
          subscribe_save_pct=15, label_protein_g=17),
    offer(product_id="quest-chips", retailer="Target", source_url="https://www.target.com/p/quest-chips/-/A-00000002",
          evidence_text="Quest Tortilla Style Protein Chips 12ct $24.99, Target Circle 20% off", pack_count=12,
          pack_price=24.99, promo_type="pct_off", promo_value=20, ends="2026-11-22"),
    offer(product_id="drumroll-donuts", retailer="Ralphs", source_url="https://www.ralphs.com/p/drumroll-mini-donuts/0000000000003",
          evidence_text="Drumroll Mini Protein Donuts 2.6 oz $3.29", pack_count=1, pack_price=3.29),
    offer(product_id="legendary-pastry", retailer="Legendary Foods", source_url="https://eatlegendary.com/products/protein-pastry",
          evidence_text="Protein Pastry 10-pack $27.60, code SAVE30 for 30% off (reported by Slickdeals 2026-11-12), $5.99 shipping under $50",
          pack_count=10, pack_price=27.60, code="SAVE30", code_pct_off=30, shipping_cost=5.99, free_shipping_min=50),
    offer(product_id="magic-spoon-pastry", retailer="Walmart", source_url="https://www.walmart.com/ip/magic-spoon-pastry/000000004",
          evidence_text="Magic Spoon Protein Pastry $0.85 clearance", pack_count=1, pack_price=0.85, is_sale_price=True),
  ], "dead_codes": []}},
 "rtd": {
  "label": "rtd", "searches": 8,
  "product_ids": ["raw-protein-rtd", "isopure-zc-40", "isopure-zc-32", "core-power-26", "core-power-elite-42",
                  "premier-protein-30", "muscle-milk-pro", "quest-shake", "oikos-pro-shake"],
  "urls": ["https://www.costco.com/premier-protein-18.product.000000005.html",
           "https://www.samsclub.com/p/core-power-elite-12pk/000000006",
           "https://www.vitaminshoppe.com/p/isopure-zero-carb-rtd-20oz/fx2",
           "https://www.target.com/p/oikos-pro-shake/-/A-00000007", "https://www.walmart.com/ip/core-power-26g/000000008"],
  "extraction": {"offers": [
    offer(product_id="premier-protein-30", retailer="Costco", source_url="https://www.costco.com/premier-protein-18.product.000000005.html",
          evidence_text="Premier Protein Shake 11 fl oz 18-pack $32.99", pack_count=18, pack_price=32.99, unit_size_oz=11,
          label_protein_g=30, membership_required=True),
    offer(product_id="core-power-elite-42", retailer="Sam's Club", source_url="https://www.samsclub.com/p/core-power-elite-12pk/000000006",
          evidence_text="Fairlife Core Power Elite 42g 14 fl oz 12 pk $44.98", pack_count=12, pack_price=44.98, unit_size_oz=14),
    offer(product_id="isopure-zc-40", retailer="The Vitamin Shoppe", source_url="https://www.vitaminshoppe.com/p/isopure-zero-carb-rtd-20oz/fx2",
          evidence_text="Isopure Zero Carb RTD 20 fl oz 12 pack $69.99, BOGO 50%", pack_count=12, pack_price=69.99,
          unit_size_oz=20, promo_type="bogo_50"),
    offer(product_id="oikos-pro-shake", retailer="Target", source_url="https://www.target.com/p/oikos-pro-shake/-/A-00000007",
          evidence_text="Oikos Pro Shake 12 fl oz $2.19", pack_count=1, pack_price=2.19, unit_size_oz=12),
    offer(product_id="core-power-26", retailer="Walmart", source_url="https://www.walmart.com/ip/core-power-26g/000000008",
          evidence_text="Core Power 26g 11.5 fl oz 12pk $24.98", pack_count=12, pack_price=24.98, unit_size_oz=11.5),
  ], "dead_codes": []}},
}

out = Path(__file__).parent / "dryrun"
out.mkdir(exist_ok=True)
for name, fx in FIX.items():
    fx.setdefault("dossier", f"(fixture dossier for {name})")
    (out / f"{name}.json").write_text(json.dumps(fx, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print("wrote", len(FIX), "fixtures")
