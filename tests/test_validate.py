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
