"""Windows Python defaults to cp1252; every file must round-trip the tier emoji as UTF-8."""
from pathlib import Path

from radar.tiers import RECORD_BADGE, TIER_EMOJI, UNVERIFIED_BADGE
from radar.util import read_json, write_json, write_text

ALL = "".join(TIER_EMOJI.values()) + RECORD_BADGE + UNVERIFIED_BADGE + "💪👍😐💸🔒🏬⚡🍫🥤📡"


def test_note_round_trip(tmp_path: Path):
    p = tmp_path / "Logs" / "emoji-test.md"
    text = f"# Tiers {ALL}\n| 🚨 STEAL | 🔥 HOT | ✅ SOLID | ❌ SKIP | 🏆 |\n"
    write_text(p, text)
    assert p.read_text(encoding="utf-8") == text
    assert p.read_bytes() == text.encode("utf-8")      # LF only, no BOM, no cp1252
    assert b"\r\n" not in p.read_bytes()


def test_json_round_trip_keeps_emoji_unescaped(tmp_path: Path):
    p = tmp_path / "x.json"
    write_json(p, {"tier": ALL})
    assert read_json(p, None) == {"tier": ALL}
    assert "🚨" in p.read_text(encoding="utf-8")


def test_no_bare_open_calls_without_encoding():
    """Guard: every open()/read_text()/write_text() in the package passes encoding."""
    import re
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for f in list((root / "radar").glob("*.py")) + [root / "deal_hunter.py"]:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\b(read_text|write_text)\(\s*\)", line) or (
                    re.search(r"(?<![\w.])open\(", line) and "encoding" not in line):
                if "def write_text" in line or "os.fdopen" in line:
                    continue
                offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert not offenders, offenders
