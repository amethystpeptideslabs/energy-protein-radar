"""Two-store stock notes (Orange + Brea): a deal is only 'unavailable' when no store has it."""
import json
import re
import subprocess
from pathlib import Path

import pytest

from radar.pricing import is_unavailable

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ("Orange pick-up: 6 In Stock; Brea: 2 In Stock (checked Nov 16)", False),
    ("Orange pick-up: Out of Stock; Brea: 3 In Stock (checked Nov 16)", False),
    ("Orange pick-up: 1 In Stock; Brea: Out of Stock (checked Nov 16)", False),
    ("Orange and Brea pick-up: Out of Stock (checked Nov 16)", True),
    ("Orange pick-up: Out of Stock; Brea: Out of Stock (checked Nov 16)", True),
    ("Orange pick-up: Temporarily Out of Stock; available in nearby stores (checked Nov 16)", True),
    ("Orange page: Product Discontinued, clearance while supplies last; call the store", True),
    ("Limited stock at Costco Anaheim", False),
    ("", False),
]


@pytest.mark.parametrize("note,gone", CASES)
def test_python_unavailable(note, gone):
    assert is_unavailable({"stock_note": note}) is gone


def test_app_uses_the_same_rule():
    src = (ROOT / "app.js").read_text(encoding="utf-8")
    fn = re.search(r"function isGone\(note\) \{.*?\n\}", src, re.S)
    assert fn, "app.js needs isGone(note)"
    js = fn.group(0) + "\nconsole.log(JSON.stringify(%s.map(([n]) => isGone(n))));" % json.dumps(CASES)
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [g for _, g in CASES]
