"""The search bar matches brand, product, flavor, store and category text the way a person types it."""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")

CASES = [
    ("Celsius Original 12oz Peach Vibe Amazon", "celsius", True),
    ("Celsius Original 12oz Peach Vibe Amazon", "peach amazon", True),
    ("Celsius Original 12oz Peach Vibe Amazon", "PEACH  Amazon ", True),
    ("Celsius Original 12oz Peach Vibe Amazon", "peach target", False),
    ("Trader Joe's", "joes", True),
    ("Trader Joe's", "joe's", True),
    ("G Fuel Energy", "gfuel", True),
    ("Ghost Energy", "", True),
    ("Ghost Energy", "   ", True),
    ("Vitamin Shoppe Orange", "vitamin shoppe", True),
    ("Café Bustelo", "cafe", True),
    ("C4 Energy", "c4", True),
    ("Quest Bar", "c4", False),
    ("Alani Nu Cherry Slush", "cherry-slush", True),
]


def test_matches_text():
    fn = re.search(r"function matchesText\(text, q\) \{.*?\n\}", APP, re.S)
    assert fn, "app.js needs a self-contained matchesText(text, q)"
    norm = re.search(r"function normText\(s\) \{.*?\n\}", APP, re.S)
    assert norm, "app.js needs normText(s)"
    js = norm.group(0) + "\n" + fn.group(0) + "\nconsole.log(JSON.stringify(%s.map(([t, q]) => matchesText(t, q))));" % json.dumps(CASES)
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [m for _, _, m in CASES]


def test_search_box_in_page():
    assert re.search(r'<input[^>]+type="search"[^>]+id="search"', HTML)
    assert 'aria-label="Search' in HTML


@pytest.mark.parametrize("fn", ["function passesView(o)", "function passes(o)"])
def test_search_filters_offers(fn):
    body = APP[APP.index(fn):APP.index(fn) + 400].split("\n")[0]
    assert "offerMatches(o)" in body


def test_search_filters_lists_and_is_not_saved():
    assert "productMatches(p)" in APP[APP.index("function renderDeals"):APP.index("function renderTabs")]
    assert "productMatches(p" in APP[APP.index("function renderRows"):APP.index("function rowHtml")]
    assert not re.search(r'store\.set\("dr\.q', APP), "a saved search would hide deals the next time the app opens"
