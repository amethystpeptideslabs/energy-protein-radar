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


def test_costco_offers_only_from_costco_com(cfg):
    from datetime import date
    from radar.util import normalize_url
    from radar.validate import validate_offers
    tracker = "https://app.warehouserunner.com/costco/2045172-bum-energy-variety-pack-18-ct-12-oz"
    official = "https://www.costco.com/bum-energy-variety-pack.product.4000000001.html"
    intel = "https://slickdeals.net/f/1-costco-celsius-24pk"
    urls = {normalize_url(u): u for u in (tracker, official, intel)}
    base = {"product_id": "bum-energy-12", "retailer": "Costco", "evidence_text": "Bum Energy 18 x 12 oz $17.97",
            "pack_count": 18, "pack_price": 17.97, "unit_size_oz": 12}
    raw = [dict(base, source_url=tracker), dict(base, source_url=official), dict(base, source_url=intel)]
    kept, dropped = validate_offers(raw, cfg, urls, {}, [], date(2026, 11, 16))
    assert [o["source_url"] for o in kept] == [official]
    assert {o["drop_reason"] for o in dropped} == {"unofficial_source"}


def test_purge_removes_tracker_offers_and_derived_records(cfg, tmp_path):
    from datetime import date
    from radar.memory import State
    from radar.pipeline import purge_blocked_sources
    s = State.load(tmp_path, cfg)
    bad = "https://app.warehouserunner.com/costco/2045172-bum-energy-variety-pack-18-ct-12-oz"
    good = "https://www.walmart.com/ip/bum-energy-12pk/1"
    s.offers = [
        {"product_id": "bum-energy-12", "retailer_key": "costco", "source_kind": "other", "source_url": bad,
         "retailer_name": "Costco", "unit_price": 0.77, "seen_date": "2026-11-16", "pack_price": 17.97, "pack_count": 18},
        {"product_id": "bum-energy-12", "retailer_key": "walmart", "source_kind": "retailer", "source_url": good,
         "retailer_name": "Walmart", "unit_price": 2.0, "seen_date": "2026-11-16", "pack_price": 23.98, "pack_count": 12},
    ]
    pm = s.memory["products"]["bum-energy-12"]
    pm["all_time_low"] = {"unit_price": 0.77, "retailer": "Costco", "date": "2026-11-16", "url": bad, "code": None}
    pm["last_best"] = {"unit_price": 0.77, "tier": "STEAL", "date": "2026-11-16"}
    s.history["bum-energy-12"] = [["2026-11-15", 2.1, "SKIP", "Walmart"], ["2026-11-16", 0.77, "STEAL", "Costco"]]
    removed = purge_blocked_sources(s, cfg, date(2026, 11, 16))
    assert [o["source_url"] for o in removed] == [bad]
    assert [o["source_url"] for o in s.offers] == [good]
    assert pm["all_time_low"] is None and pm["last_best"] is None
    assert s.history["bum-energy-12"] == [["2026-11-15", 2.1, "SKIP", "Walmart"]]
    assert purge_blocked_sources(s, cfg, date(2026, 11, 16)) == []   # idempotent


def test_mainstream_brands_dropped_but_tracked_brand_mentions_kept(cfg):
    from datetime import date
    from radar.util import normalize_url
    from radar.validate import validate_offers
    u1 = "https://www.walmart.com/ip/monster-ultra-16oz-12pk/1"
    u2 = "https://www.walmart.com/ip/reign-total-body-fuel-16oz-12pk/2"
    urls = {normalize_url(u): u for u in (u1, u2)}
    mislabeled = {"product_id": "bang-16", "retailer": "Walmart", "source_url": u1, "pack_count": 12,
                  "pack_price": 23.98, "unit_size_oz": 16,
                  "evidence_text": "Monster Energy Ultra, Sugar Free Energy Drink, 12 Pack - 16 fl oz $23.98"}
    reign = {"product_id": "reign-16", "retailer": "Walmart", "source_url": u2, "pack_count": 12,
             "pack_price": 29.76, "unit_size_oz": 16,
             "evidence_text": "Reign Total Body Fuel, White Haze, 16 fl oz, 12 Cans $29.76 (also viewed: Monster Ultra)"}
    kept, dropped = validate_offers([mislabeled, reign], cfg, urls, {}, [], date(2026, 11, 16))
    assert [o["product_id"] for o in kept] == ["reign-16"]
    assert "mainstream brand" in dropped[0]["drop_detail"]


def test_allow_terms_keep_hydration_named_energy_lines(cfg):
    assert "hydration" not in cfg.products["on-amino-energy-12"].exclude_terms
    assert "hydration" not in cfg.products["lifeaid-12"].exclude_terms
    assert "hydration" in cfg.products["ghost-energy-16"].exclude_terms
    assert "recovery" in cfg.products["kill-cliff-ignite-12"].exclude_terms
    energy = cfg.enabled("energy")
    assert len(energy) == 29 and all(p.exclude_brands for p in energy)
    assert not {"monster-16", "red-bull-12"} & {p.id for p in energy}


def test_tracked_bars_are_real_protein_bars(cfg):
    bars = [p for p in cfg.enabled("snack") if p.unit_label == "bar"]
    assert len(bars) == 10 and all(p.protein_g >= 15 for p in bars)
    for pid in ("quest-bar", "grenade-bar", "fitcrunch-bar", "david-bar", "phorm-level1-bar", "legendary-sweet-roll"):
        assert pid in cfg.products and cfg.products[pid].exclude_brands


def test_candy_brand_bar_dropped(cfg):
    from datetime import date
    from radar.util import normalize_url
    from radar.validate import validate_offers
    u1 = "https://www.walmart.com/ip/snickers-hi-protein-12ct/1"
    u2 = "https://www.target.com/p/quest-cookies-cream-12ct/-/A-53111667"
    urls = {normalize_url(u): u for u in (u1, u2)}
    candy = {"product_id": "quest-bar", "retailer": "Walmart", "source_url": u1, "pack_count": 12, "pack_price": 19.98,
             "evidence_text": "Snickers Hi Protein Bar, 20g protein, 12 count $19.98"}
    quest = {"product_id": "quest-bar", "retailer": "Target", "source_url": u2, "pack_count": 12, "pack_price": 24.99,
             "evidence_text": "Quest Nutrition 21g Protein Bar - Cookies & Cream 12ct $24.99 (also: Pure Protein bars)"}
    kept, dropped = validate_offers([candy, quest], cfg, urls, {}, [], date(2026, 11, 16))
    assert [o["source_url"] for o in kept] == [u2] and "mainstream brand" in dropped[0]["drop_detail"]


def test_store_specific_deals_must_be_in_orange_county(cfg):
    from datetime import date
    from radar.util import normalize_url
    from radar.validate import validate_offers
    u = "https://www.vitaminshoppe.com/p/alani-nu-energy-cherry-slush-12-drink-s/ala0047"
    urls = {normalize_url(u): u}
    base = {"product_id": "alani-nu-12", "retailer": "The Vitamin Shoppe", "source_url": u, "pack_count": 12,
            "pack_price": 29.99, "unit_size_oz": 12, "promo_type": "bogo_50",
            "evidence_text": "Energy Drink - Cherry Slush (12 Drinks, 12 Fl. Oz. Each) $29.99 BOGO BUY ONE, GET ONE 50% OFF"}
    oc = dict(base, local_store="Vitamin Shoppe Aliso Viejo", stock_note="Pick-Up: 8 In Stock at Aliso Viejo, CA")
    ny = dict(base, local_store="Vitamin Shoppe Brooklyn, NY", pack_price=28.99)
    web = dict(base, pack_price=27.99, stock_note="Pick-Up: 1 In Stock at Atlantic & 4th Ave, NY")
    kept, dropped = validate_offers([oc, ny, web], cfg, urls, {}, [], date(2026, 11, 16))
    assert [o["pack_price"] for o in kept] == [29.99, 27.99]
    assert kept[0]["stock_note"].endswith("Aliso Viejo, CA") and kept[1]["stock_note"] == ""
    assert dropped[0]["drop_reason"] == "out_of_area"


def test_reign_inferno_is_its_own_product_not_total_body_fuel(cfg):
    from datetime import date
    from radar.util import normalize_url
    from radar.validate import validate_offers
    u = "https://www.walmart.com/ip/Reign-Inferno-Red-Dragon-16oz-12pk/744338926"
    urls = {normalize_url(u): u}
    base = {"retailer": "Walmart", "source_url": u, "pack_count": 12, "pack_price": 29.76, "unit_size_oz": 16,
            "evidence_text": "Reign Inferno Red Dragon, Thermogenic Fuel, 16 fl oz, 12 Cans $29.76"}
    kept, dropped = validate_offers([dict(base, product_id="reign-16"), dict(base, product_id="reign-inferno-16")],
                                    cfg, urls, {}, [], date(2026, 11, 16))
    assert [o["product_id"] for o in kept] == ["reign-inferno-16"]
    assert "reign rtd" in cfg.products["reign-16"].aliases
