"""GNC weekly deals: every scan sweeps GNC's own pages and deal posts, GNC's OC stores are on file,
and GNC's own shakes (what GNC actually discounts) are tracked."""
from datetime import date

import pytest


def _plan(cfg, tmp_path, mode, slot, day):
    from radar.memory import State
    from radar.pipeline import research_plan
    return research_plan(cfg, State.load(tmp_path, cfg), mode, slot, "", None, day)


@pytest.mark.parametrize("mode,slot,day,budget", [
    ("quick", "morning", date(2026, 11, 17), 5),
    ("deep", "morning", date(2026, 11, 19), 8),
    ("quick", "midday", date(2026, 11, 19), 3),
])
def test_every_scan_plans_a_gnc_job(cfg, tmp_path, mode, slot, day, budget):
    plan = _plan(cfg, tmp_path, mode, slot, day)
    g = [j for j in plan["jobs"] if j["label"] == "gnc"]
    assert len(g) == 1 and g[0]["search_budget"] == budget
    task = g[0]["task"]
    assert "GNC" in task and "BOGO" in task and "$1" in task and "7 days" in task
    assert {p.id for p in cfg.enabled()} <= set(g[0]["product_ids"])   # any tracked item it sees


def test_gnc_job_never_drives_gnc_in_a_browser():
    from radar.research import GNC_RULES
    rules = GNC_RULES.lower()
    assert "never open gnc.com in the built-in browser" in rules
    assert "bogo_free" in rules and "pickup" in rules and "membership_required" in rules


def test_gnc_orange_county_stores_on_file(cfg):
    g = cfg.settings["retailers"]["gnc"]
    names = [s["name"] for s in g["local_stores"]]
    assert g["home_store"] == "Placentia" and names[:3] == ["Placentia", "Anaheim", "Orange"]
    assert all("CA 92" in s["address"] for s in g["local_stores"])


def test_gnc_shakes_are_tracked(cfg):
    for pid, protein in (("gnc-wheybolic-40", 40), ("gnc-total-lean-25", 25)):
        p = cfg.products[pid]
        assert p.category == "rtd" and p.protein_g == protein and "gnc" in p.retailers_priority


def test_bogo_free_with_pickup_halves_the_case(cfg):
    from radar.pricing import price_offer
    p = cfg.products["gnc-total-lean-25"]
    o = {"product_id": p.id, "retailer": "GNC", "pack_price": 34.99, "pack_count": 12, "promo_type": "bogo_free",
         "fulfillment": "pickup", "unit_size_oz": 14}
    priced = price_offer(o, p, p.ref_unit_price, cfg.settings)
    assert priced["units_in_cart"] == 24
    assert priced["unit_price"] == pytest.approx(34.99 / 24, abs=0.01)    # protein shakes: no CRV
    assert priced["tier"] == "STEAL"                                        # half the usual $2.92/bottle
