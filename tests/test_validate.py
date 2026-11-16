from datetime import date

from radar.util import normalize_url
from radar.validate import dead_codes_from_reports, flag_unverified, validate_offers
from conftest import make_offer

TODAY = date(2026, 11, 16)
URL = "https://www.amazon.com/dp/X"


def urls(*u):
    return {normalize_url(x): x for x in u}


def run(cfg, offers, dead=None, page_ages=None):
    return validate_offers(offers, cfg, urls(URL, "https://slickdeals.net/f/1"), page_ages or {}, dead or [], TODAY)


def test_unsourced_url_dropped(cfg):
    kept, dropped = run(cfg, [make_offer(source_url="https://www.amazon.com/dp/MADE-UP")])
    assert not kept and dropped[0]["drop_reason"] == "unsourced"


def test_url_normalization_tolerates_tracking_and_www(cfg):
    kept, _ = run(cfg, [make_offer(source_url="https://amazon.com/dp/X/?utm_source=x#reviews")])
    assert kept and kept[0]["source_url"] == URL


def test_stale_post_dropped_unless_promo_still_running(cfg):
    _, dropped = run(cfg, [make_offer(evidence_date="2026-10-01")])
    assert dropped[0]["drop_reason"] == "stale"
    kept, _ = run(cfg, [make_offer(evidence_date="2026-10-01", ends="2026-11-30")])
    assert kept


def test_page_age_used_when_no_evidence_date(cfg):
    _, dropped = run(cfg, [make_offer(evidence_date="")], page_ages={normalize_url(URL): "September 2, 2026"})
    assert dropped[0]["drop_reason"] == "stale"


def test_expired_promo_dropped(cfg):
    _, dropped = run(cfg, [make_offer(ends="2026-11-10")])
    assert dropped[0]["drop_reason"] == "stale"


def test_12oz_offer_in_16oz_slot_dropped(cfg):
    _, dropped = run(cfg, [make_offer(unit_size_oz=12)])
    assert dropped[0]["drop_reason"] == "wrong_product"
    _, dropped = run(cfg, [make_offer(evidence_text="Ghost Energy 12 fl oz 12-pack")])
    assert dropped[0]["drop_reason"] == "wrong_product"


def test_excluded_product_types_dropped(cfg):
    for text in ("Ghost Hydration sticks", "Ghost Energy powder tub 40 servings"):
        _, dropped = run(cfg, [make_offer(evidence_text=text)])
        assert dropped[0]["drop_reason"] == "wrong_product", text
    _, dropped = run(cfg, [make_offer(product_id="barebells", evidence_text="Vegan plant-based bar")])
    assert dropped[0]["drop_reason"] == "wrong_product"


def test_drumroll_plant_based_exception_kept(cfg):
    kept, _ = run(cfg, [make_offer(product_id="drumroll-donuts", pack_count=1, pack_price=3.29,
                                   evidence_text="Drumroll plant-based protein donuts")])
    assert kept


def test_dead_code_skipped_until_date(cfg):
    dead = [{"code": "GHOST20", "retailer": "amazon", "skip_until": "2026-12-31"}]
    _, dropped = run(cfg, [make_offer(code="ghost20", code_pct_off=20)], dead=dead)
    assert dropped[0]["drop_reason"] == "dead_code"
    expired = [{"code": "GHOST20", "retailer": "amazon", "skip_until": "2026-11-01"}]
    kept, _ = run(cfg, [make_offer(code="GHOST20", code_pct_off=20)], dead=expired)
    assert kept


def test_dead_code_reports_need_sourced_url(cfg):
    out = dead_codes_from_reports([{"code": "X1", "retailer": "Amazon", "source_url": "https://slickdeals.net/f/1",
                                    "reason": "expired"},
                                   {"code": "X2", "retailer": "Amazon", "source_url": "https://nope.com/a",
                                    "reason": "expired"}], urls("https://slickdeals.net/f/1"), cfg, TODAY)
    assert [d["code"] for d in out] == ["X1"] and out[0]["skip_until"] == "2027-01-15"


def test_unverified_flag_and_second_source(cfg):
    a = {"product_id": "ghost-energy-16", "category": "energy", "unit_price": 0.60, "source_url": "https://a.com/1"}
    flag_unverified([a], cfg)
    assert a["unverified"]
    b = {"product_id": "ghost-energy-16", "category": "energy", "unit_price": 0.61, "source_url": "https://b.com/2"}
    flag_unverified([a, b], cfg)
    assert not a["unverified"] and not b["unverified"]
    p = {"product_id": "barebells", "category": "snack", "unit_price": 0.9, "pct_vs_ref": 40.0,
         "source_url": "https://a.com/3"}
    flag_unverified([p], cfg)
    assert p["unverified"]


def test_membership_retailer_forces_lock_flag(cfg):
    kept, _ = validate_offers([make_offer(source_url="https://www.costco.com/x.html")], cfg,
                              urls("https://www.costco.com/x.html"), {}, [], TODAY)
    assert kept[0]["membership_required"] and kept[0]["retailer_key"] == "costco"


# ---------------------------------------------------------------- shopping area (Orange County)
AREA_URLS = ("https://www.amazon.com/dp/X", "https://www.heb.com/product-detail/x/1",
             "https://www.costco.com/p/-/x/1", "https://app.warehouserunner.com/costco/1-x",
             "https://www.iherb.com/pr/x/1", "https://www.kroger.com/p/x/1",
             "https://www.vitaminshoppe.com/p/x/1")


def run_area(cfg, offers):
    return validate_offers(offers, cfg, urls(*AREA_URLS), {}, [], TODAY)


def test_out_of_area_store_site_dropped(cfg):
    _, dropped = run_area(cfg, [make_offer(retailer="H-E-B", source_url=AREA_URLS[1])])
    assert dropped[0]["drop_reason"] == "outside_area"


def test_online_deal_from_any_retailer_kept(cfg):
    kept, _ = run_area(cfg, [make_offer(retailer="iHerb", source_url=AREA_URLS[4]),
                             make_offer(retailer="Amazon", source_url=AREA_URLS[0], store_location="online")])
    assert len(kept) == 2 and kept[0]["retailer_key"] == "iherb"


def test_in_store_price_needs_an_area_chain(cfg):
    _, dropped = run_area(cfg, [make_offer(retailer="Meijer", source_url=AREA_URLS[0], in_store_only=True)])
    assert dropped[0]["drop_reason"] == "outside_area"
    # chain-wide in-store promo at a chain with OC stores is fine without a city
    kept, _ = run_area(cfg, [make_offer(retailer="The Vitamin Shoppe", source_url=AREA_URLS[6],
                                        in_store_only=True, promo_type="fixed_unit_price", promo_value=1)])
    assert kept


def test_warehouse_price_needs_an_orange_county_store(cfg):
    base = dict(retailer="Costco", source_url=AREA_URLS[2], in_store_only=True, pack_count=24)
    _, dropped = run_area(cfg, [make_offer(**base)])
    assert dropped[0]["drop_reason"] == "outside_area"
    _, dropped = run_area(cfg, [make_offer(**base, store_location="Costco Liberty Hill, TX")])
    assert dropped[0]["drop_reason"] == "outside_area"
    for loc in ("Costco Fountain Valley, CA", "Tustin", "Costco #1234, 92708", "Costco La Habra"):
        kept, _ = run_area(cfg, [make_offer(**base, store_location=loc)])
        assert kept and kept[0]["store_location"] == loc, loc


def test_warehouse_tracker_counts_as_in_store(cfg):
    o = make_offer(retailer="Costco", source_url=AREA_URLS[3], pack_count=18)
    _, dropped = run_area(cfg, [o])
    assert dropped[0]["drop_reason"] == "outside_area"
    kept, _ = run_area(cfg, [make_offer(retailer="Costco", source_url=AREA_URLS[3], pack_count=18,
                                        store_location="Costco Irvine, CA")])
    assert kept and kept[0]["in_store_only"] is True


def test_store_outside_area_dropped_even_if_not_flagged_in_store(cfg):
    _, dropped = run_area(cfg, [make_offer(retailer="Ralphs", source_url=AREA_URLS[5],
                                           store_location="King Soopers Denver, CO")])
    assert dropped[0]["drop_reason"] == "outside_area"
    kept, _ = run_area(cfg, [make_offer(retailer="Ralphs", source_url=AREA_URLS[5],
                                        store_location="Ralphs Huntington Beach")])
    assert kept
