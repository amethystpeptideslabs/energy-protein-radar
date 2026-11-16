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
    assert plan["mode"] == "calibrate" and len(plan["jobs"]) == 25
    assert all("CASE" in j["task"] for j in plan["jobs"]) and plan["case_min_units"] == 12
