from datetime import date

from radar.memory import State
from radar.pipeline import detect_slot, resolve_mode


def calibrated(cfg, tmp_path):
    s = State.load(tmp_path, cfg)
    s.memory["calibrated_at"] = "2026-11-01"
    return s


def test_slot_from_github_schedule(cfg, monkeypatch):
    monkeypatch.setenv("DEAL_RADAR_SCHEDULE", "17 12 * * 4,5")
    assert detect_slot(cfg, None) == "midday"
    monkeypatch.setenv("DEAL_RADAR_SCHEDULE", "17 7 * * *")
    assert detect_slot(cfg, None) == "morning"


def test_first_run_calibrates(cfg, tmp_path):
    assert resolve_mode(cfg, State.load(tmp_path, cfg), "auto", "morning", date(2026, 11, 17))[0] == "calibrate"


def test_deep_on_monday_and_thursday_mornings(cfg, tmp_path):
    s = calibrated(cfg, tmp_path)
    assert resolve_mode(cfg, s, "auto", "morning", date(2026, 11, 16))[0] == "deep"   # Mon
    assert resolve_mode(cfg, s, "auto", "morning", date(2026, 11, 19))[0] == "deep"   # Thu
    assert resolve_mode(cfg, s, "auto", "morning", date(2026, 11, 17))[0] == "quick"  # Tue
    assert resolve_mode(cfg, s, "auto", "midday", date(2026, 11, 19))[0] == "quick"


def test_evening_noop_outside_deal_season(cfg, tmp_path):
    s = calibrated(cfg, tmp_path)
    assert resolve_mode(cfg, s, "auto", "evening", date(2026, 11, 16))[0] == "skip"
    assert resolve_mode(cfg, s, "auto", "evening", date(2026, 11, 27))[0] == "quick"   # Black Friday
    assert resolve_mode(cfg, s, "auto", "evening", date(2026, 12, 3))[0] == "skip"
