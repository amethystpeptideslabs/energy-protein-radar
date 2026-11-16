import json
from pathlib import Path

from radar.pipeline import RunOptions, run

ROOT = Path(__file__).resolve().parent.parent


def _research_file(tmp_path: Path) -> Path:
    jobs = []
    for f in sorted((ROOT / "tests" / "fixtures" / "dryrun").glob("*.json")):
        fx = json.loads(f.read_text(encoding="utf-8"))
        jobs.append({"label": fx["label"], "product_ids": fx["product_ids"], "searches": fx["searches"],
                     "urls": fx["urls"], "page_ages": fx.get("page_ages", {}),
                     "offers": fx["extraction"]["offers"], "dead_codes": fx["extraction"]["dead_codes"]})
    # a sloppy offer with missing optional fields still ingests (defaults filled)
    jobs[0]["offers"].append({"product_id": "bang-16", "retailer": "Walmart",
                              "source_url": "https://www.walmart.com/ip/Bang-Energy-16oz-12pk/000000001",
                              "evidence_text": "Bang 16oz 24 pack $39.98", "pack_count": 24, "pack_price": 39.98})
    p = tmp_path / "research.json"
    p.write_text(json.dumps({"mode": "quick", "jobs": jobs}), encoding="utf-8")
    return p


def test_ingest_runs_without_api_key(tmp_path, capsys):
    out = tmp_path / "out"
    r = run(RunOptions(ingest=_research_file(tmp_path), out=out, slot="morning", no_push=True))
    assert r.status == "ok" and r.mode == "quick"
    latest = json.loads((out / "data" / "latest.json").read_text(encoding="utf-8"))
    bang = next(p for p in latest["products"] if p["id"] == "bang-16")
    assert any(o["pack_count"] == 24 and o["is_case"] for o in bang["offers"])
    ghost = next(p for p in latest["products"] if p["id"] == "ghost-energy-16")
    assert any(o["pack_count"] == 1 and not o["is_case"] for o in ghost["offers"])   # singles still count
    status = json.loads((out / "data" / "status.json").read_text(encoding="utf-8"))
    assert status["cost_usd"] == 0 and status["searches"] == 24
    assert "[ntfy mock]" in capsys.readouterr().out


def test_plan_lists_jobs_and_case_focus(tmp_path, capsys):
    from radar.pipeline import main_from_cli
    assert main_from_cli(RunOptions(plan=True, out=tmp_path, slot="morning")) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["mode"] == "calibrate" and len(plan["jobs"]) == 55
    assert all("CASE" in j["task"] for j in plan["jobs"]) and plan["case_min_units"] == 12
    assert plan["total_search_budget"] == 110


def test_quick_and_deep_plans_are_per_category(cfg, tmp_path):
    from datetime import date
    from radar.memory import State
    from radar.pipeline import research_plan
    s = State.load(tmp_path, cfg)
    q = research_plan(cfg, s, "quick", "morning", "", None, date(2026, 11, 17))
    assert [j["label"] for j in q["jobs"]] == ["energy", "snack", "rtd"] and q["total_search_budget"] == 21
    dp = research_plan(cfg, s, "deep", "morning", "", None, date(2026, 11, 19))
    assert [j["label"] for j in dp["jobs"]] == ["energy-1", "energy-2", "snack-1", "snack-2", "rtd"]
    assert dp["total_search_budget"] == 48 and "DEEP RUN" in dp["jobs"][0]["task"]
    assert sorted(sum((j["product_ids"] for j in dp["jobs"][:2]), [])) == sorted(p.id for p in cfg.enabled("energy"))
    m = research_plan(cfg, s, "quick", "midday", "", None, date(2026, 11, 19))
    assert m["total_search_budget"] == 16 and "WEEKEND" in m["jobs"][0]["task"]


def test_quick_energy_focus_rotates_through_every_brand(cfg, tmp_path):
    from datetime import date, timedelta
    from radar.memory import State
    from radar.pipeline import research_plan
    s = State.load(tmp_path, cfg)
    energy = {p.id for p in cfg.enabled("energy")}
    focused = set()
    for k in range(3):
        job = research_plan(cfg, s, "quick", "morning", "", None, date(2026, 11, 17) + timedelta(days=k))["jobs"][0]
        assert set(job["product_ids"]) == energy                   # every brand can still be reported
        head = job["task"].split("Also report", 1)[0]
        focused |= {pid for pid in energy if f"- {pid} (" in head}
        assert "never report" in job["task"] and "Monster" in job["task"]
    assert focused == energy


def test_quick_snack_focus_rotates_and_bans_candy_bars(cfg, tmp_path):
    from datetime import date, timedelta
    from radar.memory import State
    from radar.pipeline import research_plan
    s = State.load(tmp_path, cfg)
    snacks = {p.id for p in cfg.enabled("snack")}
    focused = set()
    for k in range(2):
        job = research_plan(cfg, s, "quick", "morning", "", None, date(2026, 11, 17) + timedelta(days=k))["jobs"][1]
        assert job["label"] == "snack" and set(job["product_ids"]) == snacks
        focused |= {pid for pid in snacks if f"- {pid} (" in job["task"].split("Also report", 1)[0]}
        assert "Snickers" in job["task"] and "Clif" in job["task"]
    assert focused == snacks


def test_new_products_get_one_time_calibration_jobs(cfg, tmp_path):
    from datetime import date
    from radar.memory import State
    from radar.pipeline import research_plan
    s = State.load(tmp_path, cfg)
    for pid, pm in s.memory["products"].items():
        pm["ref_source"] = "calibrated (2 retailers)"
    s.memory["calibrated_at"] = "2026-11-16"
    s.memory["products"]["zoa-16"]["ref_source"] = "seed"
    s.memory["products"]["nocco-12"]["ref_source"] = "seed"
    plan = research_plan(cfg, s, "quick", "morning", "", None, date(2026, 11, 17))
    cal = [j for j in plan["jobs"] if j["label"].startswith("cal:")]
    assert [j["label"] for j in cal] == ["cal:zoa-16", "cal:nocco-12"] and all(j["search_budget"] == 2 for j in cal)
    assert "REGULAR" in cal[0]["task"]
    s.memory["products"]["zoa-16"]["cal_attempted"] = "2026-11-17"
    plan = research_plan(cfg, s, "quick", "morning", "", None, date(2026, 11, 18))
    assert [j["label"] for j in plan["jobs"] if j["label"].startswith("cal:")] == ["cal:nocco-12"]


def test_ingesting_a_cal_job_sets_ref_and_marks_product(tmp_path):
    out = tmp_path / "out"
    first = run(RunOptions(ingest=_research_file(tmp_path), out=out, slot="morning", no_push=True))
    assert first.status == "ok"
    u1 = "https://www.walmart.com/ip/seort/909589999"
    u2 = "https://www.target.com/p/zoa-energy-16oz-12pk/-/A-1"
    job = {"label": "cal:zoa-16", "product_ids": ["zoa-16"], "searches": 2, "urls": [u1, u2],
           "offers": [{"product_id": "zoa-16", "retailer": "Walmart", "source_url": u1, "pack_count": 12,
                       "pack_price": 29.99, "unit_size_oz": 16, "evidence_text": "ZOA Wild Orange, 16oz (12-Pack) $29.99"},
                      {"product_id": "zoa-16", "retailer": "Target", "source_url": u2, "pack_count": 12,
                       "pack_price": 31.99, "unit_size_oz": 16, "evidence_text": "ZOA Energy 16 fl oz 12pk $31.99"}]}
    f = tmp_path / "cal.json"
    f.write_text(json.dumps({"mode": "quick", "jobs": [job]}), encoding="utf-8")
    r = run(RunOptions(ingest=f, out=out, slot="morning", no_push=True))
    assert r.status == "ok"
    mem = json.loads((out / "data" / "memory.json").read_text(encoding="utf-8"))
    pm = mem["products"]["zoa-16"]
    assert pm["cal_attempted"] and pm["ref_source"].startswith("calibrated") and pm["ref_unit_price"] == 2.59   # median of $2.50 and $2.67


def test_flavor_is_kept_so_each_card_names_what_is_on_the_shelf(tmp_path):
    rf = _research_file(tmp_path)
    data = json.loads(rf.read_text(encoding="utf-8"))
    o = dict(data["jobs"][0]["offers"][-1])  # the sourced Bang 24-pack
    o["flavor"] = "Black Cherry Vanilla"
    data["jobs"][0]["offers"][-1] = o
    rf.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "out"
    run(RunOptions(ingest=rf, out=out, slot="morning", no_push=True))
    latest = json.loads((out / "data" / "latest.json").read_text(encoding="utf-8"))
    bang = next(p for p in latest["products"] if p["id"] == "bang-16")
    assert any(x.get("flavor") == "Black Cherry Vanilla" for x in bang["offers"])
    assert all("flavor" in x for x in bang["offers"])  # always present ("" when unknown)


def test_schema_asks_for_flavor():
    from radar.extract import OFFER_FIELDS
    assert OFFER_FIELDS["flavor"]["type"] == "string"
