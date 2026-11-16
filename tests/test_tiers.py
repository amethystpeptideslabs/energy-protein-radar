import pytest

from radar.tiers import energy_thresholds, energy_tier, protein_tier, protein_value_badge


@pytest.mark.parametrize("price,tier", [(1.24, "STEAL"), (1.25, "HOT"), (1.55, "HOT"), (1.56, "SOLID"),
                                        (1.85, "SOLID"), (1.86, "SKIP")])
def test_energy_16oz_boundaries(settings, price, tier):
    assert energy_tier(price, 16, settings["tiers"]["energy"]) == tier


@pytest.mark.parametrize("price,tier", [(0.93, "STEAL"), (0.94, "HOT"), (1.16, "HOT"), (1.17, "SOLID"),
                                        (1.39, "SOLID"), (1.40, "SKIP")])
def test_energy_12oz_boundaries(settings, price, tier):
    assert energy_tier(price, 12, settings["tiers"]["energy"]) == tier


def test_12oz_row_matches_16oz_scaled_by_075(settings):
    cfg = dict(settings["tiers"]["energy"])
    by = dict(cfg["by_size"])
    by.pop("12")
    scaled = energy_thresholds(12, {**cfg, "by_size": by})
    assert {k: float(v) for k, v in scaled.items()} == {"steal": 0.94, "hot": 1.16, "solid": 1.39}


@pytest.mark.parametrize("pct,tier", [(70, "STEAL"), (70.0, "STEAL"), (70.5, "HOT"), (80, "HOT"),
                                      (80.01, "SOLID"), (90, "SOLID"), (90.01, "SKIP")])
def test_protein_boundaries(settings, pct, tier):
    assert protein_tier(pct, settings["tiers"]["protein"]) == tier


def test_exactly_70pct_via_pricing(cfg, settings):
    from radar.pricing import price_offer
    from conftest import make_offer
    p = cfg.products["barebells"]
    r = price_offer(make_offer(product_id="barebells", pack_count=1, pack_price=1.40), p, 2.00, settings)
    assert r["pct_vs_ref"] == 70.0 and r["tier"] == "STEAL"
    r = price_offer(make_offer(product_id="barebells", pack_count=1, pack_price=1.41), p, 2.00, settings)
    assert r["pct_vs_ref"] == 70.5 and r["tier"] == "HOT"


def test_protein_unrated_without_ref(settings):
    assert protein_tier(None, settings["tiers"]["protein"]) == "UNRATED"


@pytest.mark.parametrize("v,badge", [(0.90, "💪"), (0.91, "👍"), (1.20, "👍"), (1.60, "😐"), (1.61, "💸")])
def test_protein_value_badge(settings, v, badge):
    assert protein_value_badge(v, settings["tiers"]["protein_value"]) == badge
