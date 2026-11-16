"""No expired sales: every sale or deal shown must have been confirmed live recently.

- A sale/deal not re-confirmed within research.sale_fresh_hours drops off (regular prices still
  carry over), past end dates drop, and not-yet-started sales stay hidden.
- Sale evidence (deal posts, sale pages) older than a week is rejected at validation.
- Each scan's plan re-checks every live sale/deal so nothing goes stale silently.
- The app hides ended or stale sales on its own if a scan fails.
"""
import json
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

from radar.memory import State, current_offers
from radar.pipeline import _price_all, fresh_deals_only, research_plan
from radar.pricing import is_sale
from radar.util import TZ, normalize_url

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 17, 6, 0, tzinfo=TZ)
TODAY = NOW.date()


def _offer(**kw):
    o = {"product_id": "alani-nu-12", "retailer": "The Vitamin Shoppe", "retailer_key": "vitamin-shoppe",
         "retailer_name": "The Vitamin Shoppe", "source_kind": "retailer",
         "source_url": "https://www.vitaminshoppe.com/p/alani-nu-energy-cherry-slush-12-drink-s/ala0047",
         "pack_count": 12, "pack_price": 29.99, "unit_size_oz": 12, "promo_type": "none", "min_qty": 1,
         "fulfillment": "pickup", "seen_date": TODAY.isoformat(), "seen_at": NOW.isoformat()}
    o.update(kw)
    return o


def _ago(hours):
    t = NOW - timedelta(hours=hours)
    return {"seen_at": t.isoformat(), "seen_date": t.date().isoformat()}


def _live(cfg, tmp_path, offers):
    s = State.load(tmp_path, cfg)
    s.offers = offers
    kept, expired = fresh_deals_only(_price_all(current_offers(s, cfg, TODAY), cfg), cfg, NOW)
    return kept, expired


def test_is_sale():
    assert is_sale({"promo_type": "bogo_50"}) and is_sale({"code": "SAVE20"})
    assert is_sale({"is_sale_price": True}) and is_sale({"coupon_clip_value": 2})
    assert is_sale({"regular_pack_price": 34.99, "pack_price": 29.99})
    assert not is_sale({"promo_type": "none", "pack_price": 29.99, "regular_pack_price": 0})


def test_sale_not_reconfirmed_within_window_drops(cfg, tmp_path):
    stale = _offer(promo_type="bogo_50", **_ago(21))
    kept, expired = _live(cfg, tmp_path, [stale])
    assert kept == [] and len(expired) == 1


def test_recent_sale_stays(cfg, tmp_path):
    kept, _ = _live(cfg, tmp_path, [_offer(promo_type="bogo_50", **_ago(3))])
    assert len(kept) == 1


def test_deal_tier_regular_price_also_needs_reconfirming(cfg, tmp_path):
    cheap = _offer(product_id="celsius-essentials-16", unit_size_oz=16, pack_price=14.98,
                   source_url="https://www.walmart.com/ip/celsius-essentials-12pk/1", retailer="Walmart",
                   retailer_key="walmart", **_ago(21))
    kept, expired = _live(cfg, tmp_path, [cheap])
    assert kept == [] and expired[0]["tier"] in ("STEAL", "HOT", "SOLID")


def test_regular_price_carries_over(cfg, tmp_path):
    kept, _ = _live(cfg, tmp_path, [_offer(**_ago(21))])   # $2.55/can: not a deal, not a sale
    assert len(kept) == 1 and kept[0]["tier"] == "SKIP"


def test_ended_and_not_started_sales_hidden(cfg, tmp_path):
    ended = _offer(promo_type="pct_off", promo_value=20, ends=(TODAY - timedelta(days=1)).isoformat())
    later = _offer(promo_type="pct_off", promo_value=20, starts=(TODAY + timedelta(days=2)).isoformat(),
                   source_url="https://www.vitaminshoppe.com/p/x/ala0015")
    ends_today = _offer(promo_type="pct_off", promo_value=20, ends=TODAY.isoformat(),
                        source_url="https://www.vitaminshoppe.com/p/y/bmn-17135")
    kept, _ = _live(cfg, tmp_path, [ended, later, ends_today])
    assert [o["source_url"] for o in kept] == [ends_today["source_url"]]


def test_week_old_sale_evidence_rejected(cfg):
    from radar.validate import validate_offers
    u1 = "https://slickdeals.net/f/1-alani-nu-bogo"
    u2 = "https://www.walmart.com/ip/alani-nu-12pk/2"
    urls = {normalize_url(u): u for u in (u1, u2)}
    old_sale = _offer(source_url=u1, retailer="Vitamin Shoppe", promo_type="bogo_50",
                      evidence_date=(date(2026, 11, 16) - timedelta(days=9)).isoformat(),
                      evidence_text="Alani Nu Energy 12 oz 12 pack BOGO 50% at Vitamin Shoppe $29.99")
    old_regular = _offer(source_url=u2, retailer="Walmart", retailer_key="walmart",
                         evidence_date=(date(2026, 11, 16) - timedelta(days=9)).isoformat(),
                         evidence_text="Alani Nu Energy 12 fl oz, 12 pack $29.98")
    kept, dropped = validate_offers([old_sale, old_regular], cfg, urls, {}, [], date(2026, 11, 16))
    assert [o["source_url"] for o in kept] == [u2]
    assert dropped[0]["drop_reason"] == "stale"


def test_plan_rechecks_every_live_sale(cfg, tmp_path):
    s = State.load(tmp_path, cfg)
    s.offers = [_offer(promo_type="bogo_50", **_ago(5)),
                _offer(product_id="celsius-essentials-16", unit_size_oz=16, pack_price=14.98, retailer="Walmart",
                       retailer_key="walmart", source_url="https://www.walmart.com/ip/celsius-essentials-12pk/1", **_ago(5)),
                _offer(source_url="https://www.vitaminshoppe.com/p/z/ala0099", **_ago(5))]  # regular: no re-check
    plan = research_plan(cfg, s, "quick", "morning", "", None, TODAY)
    v = [j for j in plan["jobs"] if j["label"] == "verify"]
    assert len(v) == 1 and v[0]["search_budget"] == 2
    assert "ala0047" in v[0]["task"] and "celsius-essentials-12pk" in v[0]["task"] and "ala0099" not in v[0]["task"]
    assert set(v[0]["product_ids"]) == {"alani-nu-12", "celsius-essentials-16"}


def test_output_marks_sales(cfg, tmp_path):
    from radar.pipeline import _slim
    assert _slim(_offer(promo_type="bogo_50"), False)["is_sale"] is True
    assert _slim(_offer(), False)["is_sale"] is False


def test_app_hides_ended_or_stale_sales():
    src = (ROOT / "app.js").read_text(encoding="utf-8")
    fn = re.search(r"function isExpired\(o, now\) \{.*?\n\}", src, re.S)
    assert fn, "app.js needs isExpired(o, now)"
    now = "2026-11-17T06:00:00-08:00"
    cases = [
        ({"is_sale": True, "seen_at": "2026-11-17T05:00:00-08:00"}, False),
        ({"is_sale": True, "seen_at": "2026-11-15T12:00:00-08:00"}, True),     # 42h: stale
        ({"tier": "HOT", "seen_at": "2026-11-15T12:00:00-08:00"}, True),
        ({"tier": "SKIP", "seen_at": "2026-11-14T12:00:00-08:00"}, False),     # regular price
        ({"is_sale": True, "seen_at": "2026-11-17T05:00:00-08:00", "ends": "2026-11-16"}, True),
        ({"is_sale": True, "seen_at": "2026-11-17T05:00:00-08:00", "ends": "2026-11-17"}, False),
        ({"is_sale": True, "seen_at": "2026-11-17T05:00:00-08:00", "starts": "2026-11-19"}, True),
    ]
    js = (fn.group(0) + f"\nconst now = new Date({json.dumps(now)});\n"
          f"console.log(JSON.stringify({json.dumps([c for c, _ in cases])}.map((o) => isExpired(o, now))));")
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [e for _, e in cases]
