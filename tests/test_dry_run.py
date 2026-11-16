import json
import re
from pathlib import Path

import jsonschema

from radar.pipeline import RunOptions, run

ROOT = Path(__file__).resolve().parent.parent


def test_dry_run_end_to_end(tmp_path, monkeypatch, capsys):
    # built at runtime so the pre-commit secret scanner never sees a key-shaped literal
    monkeypatch.setenv("NTFY_TOPIC", "deal-" + "radar-" + "SHOULD_NEVER_BE_WRITTEN_123456")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-" + "ant-" + "api03-" + "SHOULDNEVERBEWRITTEN" + "x" * 12)
    r = run(RunOptions(dry_run=True, out=tmp_path, slot="morning"))
    assert r.status == "ok" and r.mode == "calibrate"
    data = tmp_path / "data"
    for f in ("memory.json", "latest.json", "history.json", "status.json", "offers.json"):
        assert (data / f).exists(), f
    vault = tmp_path / "Obsidian-Vault"
    assert (vault / "Logs" / "2026-11-16-Deal-Run.md").exists()
    assert (vault / "00-Master-Deal-Profile.md").exists()
    assert len(list((vault / "Products").glob("*.md"))) == 55
    assert (vault / "Reference" / "Dead-Codes.md").exists()

    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert (data / "latest.json").stat().st_size < 150_000
    assert len(latest["products"]) == 55
    assert latest["heroes"]["energy"]["product_id"] == "ghost-energy-16"
    assert latest["counts"]["unverified"] == 1

    # dropped offers are reported, not shown
    log = (vault / "Logs" / "2026-11-16-Deal-Run.md").read_text(encoding="utf-8")
    for reason in ("unsourced", "stale", "wrong_product"):
        assert f"`{reason}`" in log

    # memory matches its JSON Schema
    schema = json.loads((ROOT / "schemas" / "memory.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(json.loads((data / "memory.json").read_text(encoding="utf-8")), schema)

    # secrets never land on disk; mock ntfy payload printed with topic redacted
    for f in list(data.rglob("*")) + list(vault.rglob("*")):
        if f.is_file():
            t = f.read_text(encoding="utf-8")
            assert "SHOULD_NEVER_BE_WRITTEN" not in t and not re.search(r"sk-ant-[A-Za-z0-9_-]{20,}", t), f
    out = capsys.readouterr().out
    assert "[ntfy mock]" in out and "SHOULD_NEVER_BE_WRITTEN" not in out

    # second run the same day: not first run anymore -> deep (Monday), records stay silent at same prices
    r2 = run(RunOptions(dry_run=True, out=tmp_path, slot="morning"))
    assert r2.mode == "deep" and r2.status == "ok"
