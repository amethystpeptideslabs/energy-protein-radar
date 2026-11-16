from datetime import date

from radar.memory import State, remember_alert
from radar.notify import fingerprint, plan_pushes

APP = "https://example.github.io/app/"


def o(pid, price, tier="STEAL", cat="energy", **kw):
    return {"product_id": pid, "unit_price": price, "tier": tier, "category": cat, "retailer_key": "gnc",
            "retailer_name": "GNC", "source_url": f"https://gnc.com/{pid}", "code": "", "pct_vs_ref": 50.0,
            "price_per_10g_protein": None, **kw}


def test_max_three_pushes_and_overflow_rolls_into_digest(cfg, tmp_path):
    s = State.load(tmp_path, cfg)
    steals = [o(pid, 1.0) for pid in ("ghost-energy-16", "3d-energy-16", "bang-16", "bum-energy-12",
                                       "gorilla-mind-energy-16")]
    pushes = plan_pushes(s, cfg, records=[], ranked=steals, heroes={"energy": steals[0]},
                         send_digest=True, failure=None, app_url=APP)
    assert len(pushes) == 3
    assert pushes[-1]["title"].endswith("digest") and "Also:" in pushes[-1]["message"]


def test_unverified_never_pushed(cfg, tmp_path):
    s = State.load(tmp_path, cfg)
    bad = o("ghost-energy-16", 0.50, unverified=True)
    pushes = plan_pushes(s, cfg, records=[bad], ranked=[bad], heroes={}, send_digest=False,
                         failure=None, app_url=APP)
    assert pushes == []


def test_steal_dedupe_72h(cfg, tmp_path):
    s = State.load(tmp_path, cfg)
    x = o("ghost-energy-16", 1.00)
    remember_alert(s, fingerprint(x), 4)
    pushes = plan_pushes(s, cfg, records=[], ranked=[x], heroes={}, send_digest=False, failure=None, app_url=APP)
    assert pushes == []


def test_record_push_is_priority_5_with_actions(cfg, tmp_path):
    s = State.load(tmp_path, cfg)
    r = o("ghost-energy-16", 0.99, is_record=True, previous_record={"unit_price": 1.05})
    pushes = plan_pushes(s, cfg, records=[r], ranked=[r], heroes={}, send_digest=False, failure=None, app_url=APP)
    assert pushes[0]["priority"] == 5 and len(pushes[0]["actions"]) == 2
    assert len(pushes) == 1  # the record is not double-pushed as a STEAL


def test_failure_push(cfg, tmp_path):
    s = State.load(tmp_path, cfg)
    p = plan_pushes(s, cfg, records=[], ranked=[], heroes={}, send_digest=True, failure="boom", app_url=APP)
    assert p[0]["priority"] == 3 and "boom" in p[0]["message"]
