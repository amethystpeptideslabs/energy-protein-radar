from radar.pricing import build_cart, price_offer, regular_unit_price
from conftest import make_offer


def P(cfg, pid):
    return cfg.products[pid]


def test_bogo50_two_12_packs_with_crv_is_skip(cfg, settings):
    o = make_offer(pack_price=29.99, pack_count=12, promo_type="bogo_50")
    r = price_offer(o, P(cfg, "ghost-energy-16"), 2.50, settings)
    assert r["packs_in_cart"] == 2 and r["units_in_cart"] == 24
    # 2 x 29.99 BOGO 50% = 44.985 -> $1.87/can + $0.05 CRV = $1.92 -> SKIP
    assert r["unit_price_ex_crv"] == 1.87
    assert r["unit_price"] == 1.92
    assert r["crv_total"] == 1.20
    assert r["tier"] == "SKIP"


def test_subscribe_save_plus_clip_coupon(cfg, settings):
    o = make_offer(pack_price=30.00, pack_count=12, coupon_clip_value=3, subscribe_save_pct=15)
    r = price_offer(o, P(cfg, "ghost-energy-16"), 2.50, settings)
    # conservative order: (30 - 3) * 0.85 = 22.95 + 0.60 CRV = 23.55 / 12 = 1.9625 -> 1.96
    assert r["effective_pack_total"] == 23.55
    assert r["unit_price"] == 1.96


def test_multi_buy_three_for_x(cfg, settings):
    o = make_offer(product_id="quest-chips", pack_count=1, pack_price=2.99, promo_type="multi_buy",
                   promo_value=6.00, min_qty=3)
    r = price_offer(o, P(cfg, "quest-chips"), 2.38, settings)
    assert r["packs_in_cart"] == 3 and r["units_in_cart"] == 3
    assert r["unit_price"] == 2.00
    assert r["price_per_10g_protein"] == round(2.00 / 19 * 10, 2)


def test_shipping_applies_below_free_minimum_only(cfg, settings):
    p = P(cfg, "legendary-pastry")
    below = make_offer(product_id="legendary-pastry", pack_count=10, pack_price=27.60,
                       shipping_cost=5.99, free_shipping_min=50)
    above = make_offer(product_id="legendary-pastry", pack_count=10, pack_price=55.00,
                       shipping_cost=5.99, free_shipping_min=50)
    assert price_offer(below, p, 2.76, settings)["shipping_included"] == 5.99
    assert price_offer(above, p, 2.76, settings)["shipping_included"] == 0.0
    instore = make_offer(product_id="legendary-pastry", pack_count=10, pack_price=27.60,
                         shipping_cost=5.99, in_store_only=True)
    assert price_offer(instore, p, 2.76, settings)["shipping_included"] == 0.0


def test_fixed_unit_price_dollar_can(cfg, settings):
    o = make_offer(pack_count=1, pack_price=2.99, promo_type="fixed_unit_price", promo_value=1.00,
                   in_store_only=True, limit_per_customer=6)
    r = price_offer(o, P(cfg, "ghost-energy-16"), 2.50, settings)
    assert r["unit_price"] == 1.05 and r["tier"] == "STEAL"


def test_non_stackable_code_picks_cheaper_option(cfg, settings):
    p = P(cfg, "ghost-energy-16")
    o = make_offer(pack_price=30.00, promo_type="pct_off", promo_value=10, code="BIG25", code_pct_off=25)
    c = build_cart(o, p, settings["crv"])
    assert c.used_code and not c.used_promo  # 25% code beats 10% promo
    o2 = dict(o, code_stackable=True)
    c2 = build_cart(o2, p, settings["crv"])
    assert c2.used_code and c2.used_promo
    assert c2.total < c.total


def test_crv_not_applied_to_dairy_or_large(cfg, settings):
    r = price_offer(make_offer(product_id="premier-protein-30", pack_count=18, pack_price=32.99),
                    P(cfg, "premier-protein-30"), 2.34, settings)
    assert r["crv_total"] == 0.0
    assert r["unit_price"] == 1.83


def test_playbook_has_numbers_from_python(cfg, settings):
    o = make_offer(pack_price=29.99, promo_type="bogo_50", code="SAVE5", code_amount_off=5,
                   code_stackable=True, subscribe_save_pct=15)
    r = price_offer(o, P(cfg, "ghost-energy-16"), 2.50, settings)
    text = " ".join(r["playbook"])
    assert "Add 2× 12-can pack" in text and "BOGO 50%" in text and "SAVE5" in text and "15%" in text
    assert f"${r['unit_price']:.2f}/can" in r["playbook"][-1]


def test_regular_price_ignores_sale_and_promos():
    assert regular_unit_price(make_offer(pack_price=24.00, pack_count=12)) == 2
    assert regular_unit_price(make_offer(pack_price=18.00, is_sale_price=True)) is None
    assert regular_unit_price(make_offer(pack_price=18.00, promo_type="bogo_50")) is None
    assert float(regular_unit_price(make_offer(pack_price=18.00, is_sale_price=True,
                                               regular_pack_price=30.00))) == 2.50
