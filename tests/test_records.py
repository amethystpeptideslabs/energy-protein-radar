from datetime import date

from radar.memory import State, calibrate, detect_records, update_history
from conftest import make_offer

TODAY = date(2026, 11, 16)


def state(cfg, tmp_path):
    return State.load(tmp_path, cfg)


def offer(price, **kw):
    return {"product_id": "ghost-energy-16", "unit_price": price, "tier": "HOT", "retailer_name": "GNC",
            "source_url": "https://gnc.com/x", "code": "", **kw}


def test_first_observation_is_silent_baseline(cfg, tmp_path):
    s = state(cfg, tmp_path)
    o = offer(1.50)
    assert detect_records(s, {"ghost-energy-16": o}, TODAY) == []
    assert s.memory["products"]["ghost-energy-16"]["all_time_low"]["unit_price"] == 1.50


def test_beating_record_flags_and_equal_does_not(cfg, tmp_path):
    s = state(cfg, tmp_path)
    detect_records(s, {"ghost-energy-16": offer(1.50)}, TODAY)
    assert detect_records(s, {"ghost-energy-16": offer(1.50)}, TODAY) == []
    new = offer(1.20)
    recs = detect_records(s, {"ghost-energy-16": new}, TODAY)
    assert recs == [new] and new["is_record"] and new["previous_record"]["unit_price"] == 1.50
    # a STEAL that doesn't beat the record is not a record
    assert detect_records(s, {"ghost-energy-16": offer(1.21, tier="STEAL")}, TODAY) == []


def test_unverified_never_sets_record(cfg, tmp_path):
    s = state(cfg, tmp_path)
    detect_records(s, {"ghost-energy-16": offer(1.50)}, TODAY)
    assert detect_records(s, {"ghost-energy-16": offer(0.50, unverified=True)}, TODAY) == []
    assert s.memory["products"]["ghost-energy-16"]["all_time_low"]["unit_price"] == 1.50


def test_history_keeps_daily_best(cfg, tmp_path):
    s = state(cfg, tmp_path)
    update_history(s, {"ghost-energy-16": offer(1.50)}, TODAY)
    update_history(s, {"ghost-energy-16": offer(1.40)}, TODAY)
    update_history(s, {"ghost-energy-16": offer(1.60)}, TODAY)
    assert s.history["ghost-energy-16"] == [["2026-11-16", 1.40, "HOT", "GNC"]]


def _raw(pid, retailer, price, **kw):
    return {**make_offer(product_id=pid, pack_count=1, pack_price=price, **kw), "retailer_key": retailer,
            "source_url": f"https://{retailer}.com/{pid}"}


def test_calibrate_uses_median_regular_price_and_never_sale_prices(cfg, tmp_path):
    s = state(cfg, tmp_path)
    offers = [_raw("barebells", "amazon", 2.50), _raw("barebells", "walmart", 2.30),
              _raw("barebells", "target", 2.70),
              _raw("barebells", "costco", 0.99, is_sale_price=True),          # sale: ignored
              _raw("barebells", "gnc", 1.00, promo_type="bogo_50")]           # promo: ignored
    corr = calibrate(s, cfg, offers, TODAY)
    assert s.memory["products"]["barebells"]["ref_unit_price"] == 2.50
    assert any(c["product_id"] == "barebells" and c["field"] == "ref_unit_price" and c["new"] == 2.50
               for c in corr)


def test_calibrate_needs_two_retailers_to_replace_seed(cfg, tmp_path):
    s = state(cfg, tmp_path)
    calibrate(s, cfg, [_raw("barebells", "amazon", 1.00)], TODAY)
    assert s.memory["products"]["barebells"]["ref_unit_price"] == cfg.products["barebells"].ref_unit_price


def test_calibrate_records_protein_corrections(cfg, tmp_path):
    s = state(cfg, tmp_path)
    corr = calibrate(s, cfg, [_raw("built-puff", "amazon", 2.4, label_protein_g=16),
                              _raw("built-puff", "costco", 2.3, label_protein_g=16)], TODAY)
    assert s.memory["products"]["built-puff"]["protein_verified"]["value"] == 16
    assert {"product_id": "built-puff", "field": "protein_g"}.items() <= next(
        c for c in corr if c["field"] == "protein_g").items()
    s.apply_overrides(cfg)
    assert cfg.products["built-puff"].protein_g == 16
