import json
from pathlib import Path

from radar.pricing import rank_key
from radar.validate import fulfillment

ROOT = Path(__file__).resolve().parent.parent


def test_fulfillment(cfg):
    r = cfg.settings["retailers"]
    assert fulfillment({"in_store_only": True}, r["amazon"], "retailer") == "in_store"
    assert fulfillment({}, r["target"], "retailer") == "pickup"
    assert fulfillment({}, r["costco"], "retailer") == "in_store"
    assert fulfillment({}, r["grocery-outlet"], "retailer") == "in_store"
    assert fulfillment({}, r["amazon"], "retailer") == "ship"
    assert r["grocery-outlet"]["physical"] and "instacart.com" in r["grocery-outlet"]["stock_search"]


def test_local_pickup_ranks_first_within_a_tier():
    ship = {"category": "energy", "tier": "HOT", "unit_price": 1.40, "fulfillment": "ship"}
    local = {"category": "energy", "tier": "HOT", "unit_price": 1.50, "fulfillment": "pickup"}
    steal_online = {"category": "energy", "tier": "STEAL", "unit_price": 1.10, "fulfillment": "ship"}
    assert sorted([ship, local, steal_online], key=rank_key) == [steal_online, local, ship]


def test_records_use_lowest_price_not_local_preference(tmp_path):
    from radar.pipeline import RunOptions, run
    jobs = []
    for f in sorted((ROOT / "tests" / "fixtures" / "dryrun").glob("*.json")):
        fx = json.loads(f.read_text(encoding="utf-8"))
        jobs.append({"label": fx["label"], "product_ids": fx["product_ids"], "urls": fx["urls"],
                     "offers": fx["extraction"]["offers"], "dead_codes": []})
    rf = tmp_path / "r.json"
    rf.write_text(json.dumps({"mode": "quick", "jobs": jobs}), encoding="utf-8")
    out = tmp_path / "o"
    run(RunOptions(ingest=rf, out=out, slot="morning", no_push=True))
    hist = json.loads((out / "data" / "history.json").read_text(encoding="utf-8"))
    assert hist["ghost-energy-16"][-1][1] == 1.05   # cheapest offer recorded
    latest = json.loads((out / "data" / "latest.json").read_text(encoding="utf-8"))
    assert latest["retailers"]["target"]["pickup"] is True and latest["home_area"]
