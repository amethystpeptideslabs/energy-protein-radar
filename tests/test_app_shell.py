"""The installed phone app must never run a new index.html with an old app.js.

GitHub Pages serves the shell with cache-control max-age=600, so any service-worker fetch
that goes through the HTTP cache can store a 10-minute-old file under the new cache version.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SW = (ROOT / "sw.js").read_text(encoding="utf-8")
APP = (ROOT / "app.js").read_text(encoding="utf-8")


def _body(src: str, start: str) -> str:
    i = src.index(start)
    return src[i:i + 900]


def test_install_bypasses_http_cache():
    install = _body(SW, 'addEventListener("install"')
    assert 'cache: "reload"' in install, "install must fetch the shell with cache:'reload'"
    assert not re.search(r"addAll\(SHELL\)", install), "plain addAll(SHELL) reuses stale HTTP-cached files"


def test_background_refresh_revalidates_with_server():
    swr = _body(SW, "async function staleWhileRevalidate")
    assert re.search(r'fetch\(req,\s*\{\s*cache:\s*"no-cache"', swr)


def test_page_reloads_once_when_new_version_takes_over():
    assert "controllerchange" in APP
    hook = _body(APP, "controllerchange")
    assert "location.reload()" in hook


def test_shell_version_bumped_with_this_fix():
    v = re.search(r'VERSION = "([^"]+)"', SW).group(1)
    assert v != "dr-2026-11-16g"
