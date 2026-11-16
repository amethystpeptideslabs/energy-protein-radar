"""The Drive vault note must match the app: honest stock marks and every live BOGO/sale."""
from datetime import date

from radar.obsidian import write_drive_note


def _offer(**kw):
    o = {"product_id": "alani-nu-12", "category": "energy", "retailer_name": "The Vitamin Shoppe",
         "retailer_key": "vitamin-shoppe", "source_url": "https://www.vitaminshoppe.com/p/x/ala0047",
         "unit_price": 1.92, "effective_pack_total": 46.19, "units_in_cart": 24, "packs_in_cart": 2,
         "pack_count": 12, "is_case": True, "fulfillment": "pickup", "tier": "SKIP", "promo_type": "none",
         "stock_note": "", "flavor": "", "unverified": False}
    o.update(kw)
    return o


def _note(tmp_path, ranked):
    run = {"date": date(2026, 11, 16), "mode": "quick", "status": "ok", "ranked": ranked,
           "heroes": {}, "best_by_product": {}}
    return write_drive_note(tmp_path, _cfg(), run).read_text(encoding="utf-8")


def _cfg():
    from radar.config import load_config
    return load_config()


def test_out_of_stock_is_flagged_not_checked(tmp_path):
    txt = _note(tmp_path, [_offer(product_id="bum-energy-12", tier="SOLID", promo_type="pct_off",
                                  stock_note="Aliso Viejo pick-up: Out of Stock (checked Nov 16)")])
    assert "⚠️ Aliso Viejo pick-up: Out of Stock" in txt
    assert "✅ Aliso Viejo pick-up: Out of Stock" not in txt


def test_live_bogo_listed_even_below_deal_tier(tmp_path):
    txt = _note(tmp_path, [_offer(promo_type="bogo_50", flavor="Cherry Slush",
                                  stock_note="Aliso Viejo pick-up: 8 In Stock (checked Nov 16)")])
    sec = txt.split("## 🎁 BOGO & sales right now", 1)[1]
    assert "Alani Nu Energy 12oz (Cherry Slush)" in sec and "BOGO 50%" in sec
    assert "✅ Aliso Viejo pick-up: 8 In Stock" in sec


def test_unverified_promos_stay_out(tmp_path):
    txt = _note(tmp_path, [_offer(promo_type="bogo_50", unverified=True)])
    assert "## 🎁 BOGO & sales right now" not in txt


def test_amazon_section_lists_live_amazon_deals(tmp_path):
    amz = _offer(product_id="celsius-original-12", retailer_name="Amazon", retailer_key="amazon",
                 source_kind="deal_intel", source_url="https://slickdeals.net/f/1", tier="HOT", flavor="Peach Vibe",
                 unit_price=1.16, effective_pack_total=13.89, units_in_cart=12, fulfillment="ship",
                 evidence_date="2026-11-14")
    regular = _offer(product_id="ghost-energy-16", retailer_name="Amazon", retailer_key="amazon", tier="SKIP",
                     source_url="https://amazon.com/dp/B0BR96LQ8B", fulfillment="ship")
    txt = _note(tmp_path, [amz, regular])
    sec = txt.split("## 🛒 Amazon deals", 1)[1].split("\n## ", 1)[0]
    assert "Celsius Original 12oz (Peach Vibe)" in sec and "posted 2026-11-14" in sec
    assert "Ghost" not in sec


def test_no_amazon_section_without_amazon_deals(tmp_path):
    assert "## 🛒 Amazon deals" not in _note(tmp_path, [_offer(tier="HOT")])
